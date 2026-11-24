"""Build <net>/topology.json (routers, links, locations, externals, customers) from <net>/raw/ + <net>/config.json.

usage: python build_topology.py <net-dir>

Inputs in <net>/raw/ (all optional except ps_out/rg_aliases/alive):
  ps_out.txt          sc_prefixscan:  "<a> <b> <alias>/<len>"  alias is on a's router; alias/b are a link's two ends
  rg_aliases*.txt     sc_radargun -d 1: address pairs sharing an IP-ID counter (same router); several files merge
  alive.txt           live addresses from the sweep (used for the loopback census)
  lbloc.json          [[loopback, last hop before it, n], ...]  from ingest_local.py
  placement.json      {ip: {probe_metro: min_rtt_ms}}           from place_globalping.py / place_atlas.py
  labels.json         {ip: pop}  manual or legacy placements, used only when an address has no latency data
  rdns.json           {ip: [ptr]}                                from bootstrap.py / rdns.py
  ix_ports.json       IX ports (PeeringDB + bgp.he.net)          from bootstrap.py
  customers.json      from build_customers.py
  extra_evidence.json hypothesis-test results (links/devices/retired), written by hand from test output

Deterministic: same inputs -> byte-identical topology.json.
"""
import collections, ipaddress, json, pathlib, sys

NET = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
RAW = NET / "raw"
CFG = json.loads((NET / "config.json").read_text())
LOOPBACKS = [ipaddress.ip_network(n) for n in CFG.get("loopbacks", [])]
PINNED = {ip: tuple(v) for ip, v in CFG.get("pins", {}).items()}          # ip -> (pop, label)
PL = CFG.get("placement", {})
NEAR = PL.get("near_ms", 1.5)
METRO = PL.get("metro_to_pop", {})                                        # metro -> {pop, max_ms, note}
REGIONAL = PL.get("regional", {})                                         # metro -> regional pop code
TRANSIT = CFG.get("transit", {})                                          # {org, ic: {ip: far_router}, far_ptr_suffix}
IX_METRO = CFG.get("ix_metro", {})                                        # PeeringDB city -> pop


def jl(name, default):
    p = RAW / name
    return json.loads(p.read_text()) if p.exists() else default


def key(ip):
    return tuple(int(x) for x in ip.split("."))


def is_lb(ip):
    return any(ipaddress.ip_address(ip) in n for n in LOOPBACKS)


def mates(ip):
    """The other address of the /31 and of the /30 that ip sits in (point-to-point partners)."""
    n = int(ipaddress.ip_address(ip))
    out = [n ^ 1]
    if n % 4 in (1, 2):
        out.append(n + 1 if n % 4 == 1 else n - 1)
    return [str(ipaddress.ip_address(x)) for x in out]


# ---- union-find over aliases -------------------------------------------------
par = {}
def find(x):
    par.setdefault(x, x)
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        par[max(ra, rb, key=key)] = min(ra, rb, key=key)

links = set()
for line in (RAW / "ps_out.txt").read_text().splitlines():
    t = line.split()
    if len(t) != 3 or "/" not in t[2]:
        continue
    a, b, alias = t[0], t[1], t[2].split("/")[0]
    union(a, alias)
    find(b)
    links.add((alias, b))
for f in sorted(RAW.glob("rg_aliases*.txt")):
    for line in f.read_text().splitlines():
        t = line.split()
        if len(t) >= 2 and t[0].count(".") == 3 and t[1].count(".") == 3:
            union(t[0], t[1])
alive = sorted({l.strip() for l in (RAW / "alive.txt").read_text().splitlines() if l.strip()}, key=key)
for ip in alive:
    if is_lb(ip):
        find(ip)  # every live loopback is a router, even with no interface tied to it yet
groups = collections.defaultdict(set)
for x in list(par):
    groups[find(x)].add(x)

# ---- placement ---------------------------------------------------------------
rtt = jl("placement.json", {})
labels = jl("labels.json", {})


def place(ips):
    """(pop, evidence). A pin wins; else the member with the lowest probe RTT, by the config rules."""
    for ip in sorted(ips, key=key):
        if ip in PINNED:
            return PINNED[ip][0], f"{ip} is {PINNED[ip][1]}"
    best = None
    for ip in ips:
        for metro, ms in rtt.get(ip, {}).items():
            if best is None or (ms, metro, key(ip)) < (best[1], best[0], key(best[2])):
                best = (metro, ms, ip)
    if best is None:
        for ip in sorted(ips, key=key):
            if ip in labels:
                return labels[ip], f"{ip} manual/legacy label"
        return "UNK", "no latency data"
    metro, ms, ip = best
    ev = f"{ip} {ms} ms from {metro} probe"
    rule = METRO.get(metro, {})
    if ms <= NEAR:
        return rule.get("pop", metro), ev
    if rule and ms <= rule.get("max_ms", NEAR):
        return rule["pop"], ev + (f" ({rule['note']})" if rule.get("note") else "")
    if metro in REGIONAL:
        return REGIONAL[metro], ev + f" (regional: {REGIONAL[metro]})"
    return "UNK", ev


# ---- routers (keyed by loopback until names are final) ----------------------
# Without a configured loopback block, every group with 2+ interfaces is treated as a router,
# keyed by its lowest address. With one, only groups holding a loopback are routers.
lbloc = {d: last for d, last, _ in jl("lbloc.json", [])}
R, owner = {}, {}
for members in groups.values():
    lbs = sorted((m for m in members if is_lb(m)), key=key)
    if LOOPBACKS and not lbs:
        continue
    if not LOOPBACKS and len(members) < 2:
        continue
    lo = lbs[0] if lbs else min(members, key=key)
    pop, ev = place(members)
    R[lo] = {"pop": pop, "loopback": lo, "evidence": ev, "interfaces": sorted(members, key=key),
             "ports": sorted(f"{PINNED[m][1]} {m}" for m in members if m in PINNED), "extra_loopbacks": lbs[1:]}
    for m in members:
        owner[m] = lo

pairs, downstream = collections.defaultdict(set), collections.Counter()
for a, b in links:
    ra, rb = owner.get(a), owner.get(b)
    if ra and rb and ra != rb:
        (x, xa), (y, ya) = sorted(((ra, a), (rb, b)), key=lambda t: key(t[0]))
        pairs[(x, y)].add(f"{xa} - {ya}")
    elif ra or rb:
        downstream[ra or rb] += 1

# unlinked routers: hang them off the router their loopback trace ended behind (or its link mate's router)
linked = {x for p in pairs for x in p}
inferred = set()
for lo in R:
    prev = lbloc.get(lo)
    if lo in linked or not prev:
        continue
    up = owner.get(prev) or next((owner[m] for m in mates(prev) if m in owner), None)
    if up and up != lo:
        inferred.add((up, lo, prev))

# routers with no location take their neighbours' PoP, marked with "?"
adj = collections.defaultdict(set)
for x, y in pairs:
    adj[x].add(y); adj[y].add(x)
for x, y, _ in inferred:
    adj[x].add(y); adj[y].add(x)
changed = True
while changed:
    changed = False
    for lo in sorted(R, key=key):
        if R[lo]["pop"] != "UNK":
            continue
        known = sorted({R[n]["pop"].rstrip("?") for n in adj[lo] if R[n]["pop"] != "UNK"})
        if len(known) == 1:
            R[lo]["pop"] = known[0] + "?"
            R[lo]["evidence"] += f"; only neighbours are in {known[0]}"
            changed = True

name = {lo: f"{r['pop'].rstrip('?')}-{lo.split('.')[-1]}" for lo, r in R.items()}
routers = [dict({k: r[k] for k in ("pop", "loopback", "evidence", "ports", "interfaces", "extra_loopbacks")},
                id=name[lo], downstream_devices=downstream.get(lo, 0)) for lo, r in R.items()]
order = ("id", "pop", "loopback", "evidence", "ports", "downstream_devices", "interfaces", "extra_loopbacks")
routers = [{k: r[k] for k in order} for r in routers]

topo = {
    "asn": CFG["asn"], "name": CFG["name"],
    "method": "local scamper (traces, fping sweep, sc_radargun IP-ID, sc_prefixscan /31-/30 mates); external probes for location",
    "routers": sorted(routers, key=lambda r: (r["pop"].rstrip("?"), key(r["loopback"]))),
    "links": sorted(({"a": name[x], "b": name[y], "addresses": sorted(v), "kind": "proven"} for (x, y), v in pairs.items()),
                    key=lambda l: (l["a"], l["b"])),
    "inferred_links": sorted(({"a": name[x], "b": name[y], "via": p, "kind": "inferred (loopback trace)"} for x, y, p in inferred),
                             key=lambda l: (l["a"], l["b"])),
}
own_id = {i: r["id"] for r in topo["routers"] for i in r["interfaces"]}
ex = jl("extra_evidence.json", {})
if ex:
    topo["extra_links"] = [dict(l, a=own_id[l["a_ip"]], b=own_id[l["b_ip"]]) for l in ex.get("links", [])
                           if l["a_ip"] in own_id and l["b_ip"] in own_id]
    topo["other_devices"] = [dict(d, behind_router=own_id.get(d["behind"])) for d in ex.get("devices", [])]
    topo["retired_interfaces"] = ex.get("retired", [])
cust = jl("customers.json", None)
if cust is not None:
    valid = {r["id"] for r in routers}
    for c in cust:
        c["attach"] = [a for a in c["attach"] if a["router"] in valid]
    topo["customers"] = cust

# ---- ASN family: which family ASN each router belongs to, and links between them -------------
FAMILY = CFG.get("asns", [CFG["asn"]])
origins = sorted(((ipaddress.ip_network(p), a) for p, a in jl("prefix_origins.json", {}).items()), key=lambda t: -t[0].prefixlen)
if len(FAMILY) > 1 and origins:
    def origin_of(ip):
        a = ipaddress.ip_address(ip)
        return next((asn for n, asn in origins if a in n), None)
    for r in topo["routers"]:
        votes = collections.Counter(o for o in map(origin_of, r["interfaces"]) if o)
        r["asn"] = votes.most_common(1)[0][0] if votes else None
    asn_of = {r["id"]: r.get("asn") for r in topo["routers"]}
    for l in topo["links"]:
        if asn_of[l["a"]] and asn_of[l["b"]] and asn_of[l["a"]] != asn_of[l["b"]]:
            l["inter_as"] = [asn_of[l["a"]], asn_of[l["b"]]]
    topo["asns"] = FAMILY

# ---- enrichment: reverse DNS, link RTT, external interfaces --------------------
rdns = {k: v[0].rstrip(".") for k, v in jl("rdns.json", {}).items() if v}
byid = {r["id"]: r for r in topo["routers"]}
for r in topo["routers"]:
    r["ptr"] = {i: rdns[i] for i in r["interfaces"] if i in rdns}


def router_rtt(r):
    m = {}
    for i in r["interfaces"]:
        for metro, ms in rtt.get(i, {}).items():
            m[metro] = min(ms, m.get(metro, 1e9))
    return m


# Link RTT estimate: min over probe metros of rtt(A)+rtt(B). Close to the truth when a probe sits next to
# one end; high otherwise. A |rtt(A)-rtt(B)| lower bound was tried and dropped (routing asymmetry breaks it).
for l in topo["links"]:
    a, b = router_rtt(byid[l["a"]]), router_rtt(byid[l["b"]])
    common = sorted(set(a) & set(b))
    if common:
        m = min(common, key=lambda m: (a[m] + b[m], m))
        l["rtt_est_ms"] = round(a[m] + b[m], 1)
        l["rtt_basis"] = f"probe in {m}: {a[m]} + {b[m]} ms"
topo["rtt_method"] = "min over probe metros of rtt(A)+rtt(B); overestimates when no probe is at either end"

ext = []
for r in topo["routers"]:
    for i in r["interfaces"]:
        if i in TRANSIT.get("ic", {}):
            sfx = TRANSIT.get("far_ptr_suffix", "")
            far = next((m for m in mates(i) if sfx and rdns.get(m, "").endswith(sfx)), mates(i)[0])
            ext.append({"router": r["id"], "kind": "transit", "org": TRANSIT["org"], "far_router": TRANSIT["ic"][i],
                        "near_ip": i, "near_ptr": rdns.get(i), "far_ip": far, "far_ptr": rdns.get(far),
                        "evidence": "alias resolution + transit LG BGP neighbour"})
for p in jl("ix_ports.json", []):
    owner_r = own_id.get(p["local_ip"])
    evidence = "alias resolution"
    if not owner_r:
        pop = IX_METRO.get(p["city"])
        cands = [r["id"] for r in topo["routers"] if r["pop"].rstrip("?") == pop]
        if len(cands) == 1:
            owner_r, evidence = cands[0], "only router seen in this metro (port did not answer probes)"
        else:
            evidence = "no router tied to this port" if not cands else f"{len(cands)} routers in metro; port not aliased"
    ext.append({"router": owner_r, "kind": "ix", "org": p["ix"], "near_ip": p["local_ip"], "near_ptr": rdns.get(p["local_ip"]),
                "speed_mbps": p.get("speed_mbps"), "route_server": p.get("rs_peer"), "he_ip": (p.get("he_ips") or [None])[0],
                "participants": p.get("participants"), "evidence": evidence + "; listed in " + p.get("source", "PeeringDB")})
topo["externals"] = sorted(ext, key=lambda e: (e["router"] or "~", e["kind"], e["org"]))
for c in topo.get("customers", []):
    c["edge_ptr"] = {e: rdns[e] for e in c.get("edge", []) if e in rdns}

out = NET / "topology.json"
out.write_text(json.dumps(topo, indent=1) + "\n", newline="\n")
print(f"{len(topo['routers'])} routers, {len(topo['links'])} proven links, {len(topo['inferred_links'])} inferred -> {out}")
