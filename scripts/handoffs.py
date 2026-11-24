"""How does each customer device connect? Per customer: attachment router, handoff subnet, which side is whose,
latency past the operator's router, PTRs, and how much of its space actually arrives through the operator.

usage: python handoffs.py <net-dir> plan       -> raw/handoff_targets.txt + raw/handoff_rows.txt for handoff_probe.sh
       sudo sh handoff_probe.sh <net-dir>      (local: pings + IP-ID alias rows; no rate limits)
       python handoffs.py <net-dir> report     -> raw/handoffs.json and a printed table

Inputs: topology.json (customers with attach routers and edge addresses), raw/customer_inventory.json,
raw/handoff_probe/ (after the probe), raw/rdns.json if present. Upstream share uses RIPEstat (free).

Reading the extra latency: it is min RTT to the customer edge minus min RTT to the operator router's interface,
both from the same local machine. < 1 ms: same building or short fibre. 1-5 ms: metro or regional fibre, or a
radio hop. > 5 ms: long haul, a radio chain, or a customer router slow to answer ICMP (control-plane replies
are deprioritised, so treat single numbers with care and compare against the customer's other addresses).
"""
import collections, ipaddress, json, pathlib, sys, time, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
MODE = sys.argv[2] if len(sys.argv) > 2 else "report"
RAW = NET / "raw"
topo = json.loads((NET / "topology.json").read_text())
FAMILY = set(topo.get("asns", [topo["asn"]]))
routers = {r["id"]: r for r in topo["routers"]}
owner = {i: r["id"] for r in topo["routers"] for i in r["interfaces"]}
cust = {c["asn"]: c for c in topo.get("customers", [])}
OWN_NETS = [ipaddress.ip_network(p) for p in (RAW / "prefixes.txt").read_text().split()] if (RAW / "prefixes.txt").exists() else []


def mates(ip):
    n = int(ipaddress.ip_address(ip))
    out = [(31, str(ipaddress.ip_address(n ^ 1)))]
    if n % 4 in (1, 2):
        out.append((30, str(ipaddress.ip_address(n + 1 if n % 4 == 1 else n - 1))))
    return out


def handoff_guess(c):
    """For each edge address: is a /31 or /30 partner a known interface of the attach router?"""
    res = []
    att = {a["router"] for a in c["attach"]}
    for e in c.get("edge", [])[:2]:
        hit = next(((ln, m) for ln, m in mates(e) if owner.get(m) in att), None)
        res.append({"edge": e, "router_side": hit[1] if hit else None, "len": hit[0] if hit else None,
                    "numbering": "operator space" if hit and any(ipaddress.ip_address(e) in n for n in OWN_NETS) else
                                 ("customer space" if hit else "not found next to the router (edge replies from another address)")})
    return res


if MODE == "plan":
    targets, rows = set(), []
    for asn, c in sorted(cust.items()):
        if not c["attach"]:
            continue
        r = routers[c["attach"][0]["router"]]
        for e in c.get("edge", [])[:2]:
            targets.add(e)
            for _, m in mates(e):
                targets.add(m)
            rows.append(" ".join([e] + [m for _, m in mates(e)] + [r["loopback"]]))
        # the router's interface that the trace came in on is the nearest operator-side reference point
        targets.add(r["loopback"])
    (RAW / "handoff_targets.txt").write_text("\n".join(sorted(targets, key=lambda s: ipaddress.ip_address(s))) + "\n", newline="\n")
    (RAW / "handoff_rows.txt").write_text("\n".join(rows) + "\n", newline="\n")
    print(f"{len(targets)} addresses to ping, {len(rows)} alias rows -> run handoff_probe.sh")
    sys.exit()

# ---- report ------------------------------------------------------------------
P = RAW / "handoff_probe"
rtt = json.loads((P / "rtt.json").read_text()) if (P / "rtt.json").exists() else {}
alias_pairs = set()
if (P / "al.txt").exists():
    for line in open(P / "al.txt"):
        t = line.split()
        if len(t) >= 2:
            alias_pairs.add(frozenset(t[:2]))
rdns = {k: v[0].rstrip(".") for k, v in json.loads((RAW / "rdns.json").read_text()).items() if v} if (RAW / "rdns.json").exists() else {}


def stat(p):
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen("https://stat.ripe.net/data/" + p, timeout=90)).get("data", {})
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


inv = {c["asn"]: c for c in json.loads((RAW / "customer_inventory.json").read_text())}
out = []
for asn, c in sorted(cust.items()):
    row = {"asn": asn, "name": c["name"], "attach": [a["router"] for a in c["attach"]], "other_upstreams": c.get("other_upstreams", [])}
    # upstream share: per prefix, which ASN sits just before the customer in RIS collector paths
    share = collections.Counter()
    per_prefix = {}
    for p in inv.get(asn, {}).get("prefixes", [])[:12]:
        cnt = collections.Counter()
        for rrc in stat(f"looking-glass/data.json?resource={p}").get("rrcs", []):
            for e in rrc.get("peers", []):
                s = e["as_path"].split()
                if len(s) > 1 and s[-1] == str(asn):
                    cnt[int(s[-2])] += 1
        if cnt:
            via_op = sum(v for k, v in cnt.items() if k in FAMILY) / sum(cnt.values())
            per_prefix[p] = round(via_op, 2)
            share["operator"] += via_op
            share["n"] += 1
    row["prefixes_checked"] = share["n"]
    row["operator_path_share"] = round(share["operator"] / share["n"], 2) if share["n"] else None
    row["prefixes_mostly_via_operator"] = sorted(p for p, v in per_prefix.items() if v >= 0.5)
    hs = []
    if c["attach"]:
        r = routers[c["attach"][0]["router"]]
        for h in handoff_guess(c):
            e, rs = h["edge"], h["router_side"]
            h["edge_ptr"] = rdns.get(e)
            if not rs:  # test the edge's mates against the router loopback
                for ln, m in mates(e):
                    if frozenset((m, r["loopback"])) in alias_pairs:
                        h.update(router_side=m, len=ln, numbering="found by IP-ID alias test")
            h["router_side_alias_confirmed"] = bool(h["router_side"]) and (h["router_side"] in r["interfaces"] or
                                                                           frozenset((h["router_side"], r["loopback"])) in alias_pairs)
            ref = rtt.get(h["router_side"]) if h["router_side"] else None
            ref = ref if ref is not None else rtt.get(r["loopback"])
            if rtt.get(e) is not None and ref is not None:
                h["extra_ms_past_router"] = round(rtt[e] - ref, 2)
            hs.append(h)
    row["handoffs"] = hs
    out.append(row)
(RAW / "handoffs.json").write_text(json.dumps(out, indent=1) + "\n", newline="\n")

print(f"{'customer':34s} {'router':8s} {'handoff':34s} {'+ms':>6s}  {'via-op':>6s}  other upstreams")
for r in out:
    h = r["handoffs"][0] if r["handoffs"] else {}
    ho = (f"{h.get('router_side')} / {h['edge']} (/{h['len']})" if h.get("router_side") else
          (f"edge {h['edge']} (subnet not seen)" if h else "-"))
    xm = h.get("extra_ms_past_router")
    sh = r["operator_path_share"]
    print(f"AS{r['asn']:<7} {r['name'][:25]:25s} {','.join(r['attach']) or '-':8s} {ho:34s} "
          f"{('%.1f' % xm) if xm is not None else '':>6s}  {('%d%%' % (sh * 100)) if sh is not None else '':>6s}  "
          f"{','.join(map(str, r['other_upstreams'])) or '-'}")
