"""Stage 6 (free APIs): history, to generate hypotheses about the current map.   usage: python history.py <net-dir>

Writes <net>/raw/:
  history_neighbours.json   upstreams and downstream count every 2 years since 2010 (RIPEstat asn-neighbours query_time)
  history_origins.json      per announced prefix: which ASNs originated it and when (RIPEstat routing-history).
                            Earlier origins of today's prefixes point at networks the target absorbed.
  history_atlas_traces.json router hops seen in OTHER people's public RIPE Atlas traceroutes to the target's space,
                            with first/last dates and previous hops (public results: no key needed)
Then prints historical router adjacencies that are NOT in today's topology. Each is a hypothesis to test locally:
is the /31 still alive, which routers own its two ends, does traffic use it? See SKILL.md "History".
Archived web pages (old network maps, PoP lists) are not fetched here: hand that to a cheap research subagent.
"""
import collections, concurrent.futures as cf, datetime, ipaddress, json, pathlib, sys, time, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
RAW = NET / "raw"
ASN = json.loads((NET / "config.json").read_text())["asn"]


def get(u):
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(u, timeout=120))
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


def stat(p):
    return get("https://stat.ripe.net/data/" + p).get("data", {})


hist = {}
for y in range(2010, datetime.date.today().year + 1, 2):
    n = stat(f"asn-neighbours/data.json?resource=AS{ASN}&query_time={y}-06-01T00:00").get("neighbours", [])
    left = sorted((x for x in n if x["type"] == "left"), key=lambda x: -x.get("power", 0))
    hist[y] = {"upstreams": [x["asn"] for x in left][:6], "downstreams": len([x for x in n if x["type"] == "right"])}
(RAW / "history_neighbours.json").write_text(json.dumps(hist, indent=1) + "\n", newline="\n")

prefixes = [l.strip() for l in open(RAW / "prefixes.txt") if l.strip()]
origins = {}
for p in prefixes:
    rows = []
    for o in stat(f"routing-history/data.json?resource={p}&min_peers=3").get("by_origin", []):
        for pf in o.get("prefixes", []):
            ts = pf.get("timelines", [])
            if ts:
                rows.append({"origin": int(o["origin"]), "prefix": pf["prefix"],
                             "first": min(t["starttime"] for t in ts)[:10], "last": max(t["endtime"] for t in ts)[:10]})
    origins[p] = sorted(rows, key=lambda r: r["first"])
(RAW / "history_origins.json").write_text(json.dumps(origins, indent=1) + "\n", newline="\n")

own = [ipaddress.ip_network(p) for p in prefixes]


def inside(ip):
    return bool(ip) and ":" not in ip and any(ipaddress.ip_address(ip) in n for n in own)


ms = {}
for n in ipaddress.collapse_addresses(own):
    stem = ".".join(str(n.network_address).split(".")[: max(1, n.prefixlen // 8)])
    url = f"https://atlas.ripe.net/api/v2/measurements/?target__startswith={stem}&type=traceroute&af=4&page_size=500&fields=id,target,description"
    while url:
        d = get(url)
        for m in d.get("results", []):
            if inside(m["target"]) and "netmap" not in (m.get("description") or ""):
                ms[m["id"]] = m
        url = d.get("next")
hops = collections.defaultdict(lambda: {"first": None, "last": None, "n": 0, "prev": collections.Counter()})
with cf.ThreadPoolExecutor(8) as ex:
    for rs in ex.map(lambda i: get(f"https://atlas.ripe.net/api/v2/measurements/{i}/results/"), ms):
        for r in rs if isinstance(rs, list) else []:
            ts, seq = r.get("timestamp"), []
            for h in r.get("result", []):
                z = [x for x in h.get("result", []) if x.get("from")]
                seq.append(z[0]["from"] if z else None)
            for i, ip in enumerate(seq):
                if inside(ip) and ip != r.get("dst_addr"):
                    H = hops[ip]
                    H["n"] += 1
                    H["first"] = min(filter(None, [H["first"], ts]))
                    H["last"] = max(filter(None, [H["last"], ts]))
                    p = next((x for x in reversed(seq[:i]) if x), None)
                    if p:
                        H["prev"][p] += 1
out = {k: {"first": v["first"], "last": v["last"], "n": v["n"], "prev": v["prev"].most_common(5)} for k, v in hops.items()}
(RAW / "history_atlas_traces.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", newline="\n")
print(f"{len(ms)} public traceroute measurements, {len(out)} historical router hops")

topo_f = NET / "topology.json"
if topo_f.exists():
    topo = json.loads(topo_f.read_text())
    owner = {i: r["id"] for r in topo["routers"] for i in r["interfaces"]}
    cur = {tuple(sorted((l["a"], l["b"]))) for l in topo["links"] + topo.get("extra_links", [])}

    def ym(t):
        return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m") if t else "-"

    print("historical adjacencies not in today's map (hypotheses to test):")
    for ip, v in sorted(out.items(), key=lambda kv: kv[1]["first"] or 0):
        for p, _ in v["prev"]:
            a = owner.get(p, f"old {p}" if inside(p) else None)
            b = owner.get(ip, f"old {ip}")
            if a and a != b and tuple(sorted((a, b))) not in cur:
                print(f"  {a:>20} -> {b:<20} {ym(v['first'])}..{ym(v['last'])}  ({p} > {ip})")
