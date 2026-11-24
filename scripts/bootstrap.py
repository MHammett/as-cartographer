"""Stage 1 (free public APIs, no probing): everything the later stages need to know before touching the network.

usage: python bootstrap.py <net-dir> AS<n> [AS<n> ...]     (list every ASN of the company: see family.py)

Writes <net>/raw/:
  prefixes.txt            announced IPv4 prefixes of all the ASNs given (RIPEstat)
  prefix_origins.json     {prefix: originating ASN}, used to tag routers by ASN
  probe24.txt             one address (.1) per /24 of that space, for the first local traceroute pass
  neighbours.json         upstreams (left), downstreams (right), uncertain, with power (RIPEstat asn-neighbours)
  customer_inventory.json every neighbour AS that lists the target as an upstream, with its prefixes and other upstreams
  customer_targets.txt    one address per customer /24 (up to 4 per prefix), for local customer traces
  ix_ports.json           the target's IX ports (PeeringDB netixlan) with speed, route-server flag and HE's IP on that IX
  facilities.json         PeeringDB facilities
and <net>/config.json if absent (asn, name, empty pins/placement; fill in later stages).
Rate: a few dozen API calls; RIPEstat and PeeringDB need no key.
"""
import concurrent.futures as cf, ipaddress, json, pathlib, sys, time, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
ASNS = [int(a.upper().lstrip("AS")) for a in sys.argv[2:]]
RAW = NET / "raw"
RAW.mkdir(parents=True, exist_ok=True)


def get(u, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "as-cartographer"}), timeout=90))
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


def stat(path):
    return get("https://stat.ripe.net/data/" + path).get("data", {})


def write(name, obj):
    p = RAW / name
    p.write_text((json.dumps(obj, indent=1) if not isinstance(obj, str) else obj) + ("\n" if not isinstance(obj, str) else ""), newline="\n")


# ---- prefixes and /24 probe list --------------------------------------------
origin = {}
for a in ASNS:  # several ASNs = one company's network (see family.py); each prefix remembers its origin
    for p in stat(f"announced-prefixes/data.json?resource=AS{a}").get("prefixes", []):
        if ":" not in p["prefix"]:
            origin.setdefault(p["prefix"], a)
prefixes = sorted(origin, key=lambda p: ipaddress.ip_network(p))
write("prefix_origins.json", {p: origin[p] for p in prefixes})
probe = []
for n in ipaddress.collapse_addresses(ipaddress.ip_network(p) for p in prefixes):
    for s in ([n] if n.prefixlen >= 24 else n.subnets(new_prefix=24)):
        probe.append(str(next(s.hosts(), s.network_address)))
write("prefixes.txt", "\n".join(prefixes) + "\n")
write("probe24.txt", "\n".join(probe) + "\n")

# ---- neighbours and customer inventory --------------------------------------
nb = []
for a in ASNS:
    nb += stat(f"asn-neighbours/data.json?resource=AS{a}").get("neighbours", [])
write("neighbours.json", nb)
cand = sorted({x["asn"] for x in nb if x["type"] in ("right", "uncertain")} - set(ASNS))


def one(asn):
    ov = stat(f"as-overview/data.json?resource=AS{asn}")
    pf = [p["prefix"] for p in stat(f"announced-prefixes/data.json?resource=AS{asn}").get("prefixes", []) if ":" not in p["prefix"]]
    ups = [(x["asn"], x.get("power", 0)) for x in stat(f"asn-neighbours/data.json?resource=AS{asn}").get("neighbours", []) if x["type"] == "left"]
    return {"asn": asn, "holder": ov.get("holder", ""), "prefixes": sorted(pf), "upstreams": sorted(ups, key=lambda t: -t[1])}


with cf.ThreadPoolExecutor(6) as ex:
    rows = list(ex.map(one, cand))
# a customer lists the target as an upstream. Large transit networks show up here as "right" neighbours through
# route leaks or collector artefacts; drop anything announcing more than 100 prefixes and say so.
cust = [r for r in rows if any(u in ASNS for u, _ in r["upstreams"]) and len(r["prefixes"]) <= 100]
dropped = [r["asn"] for r in rows if any(u in ASNS for u, _ in r["upstreams"]) and len(r["prefixes"]) > 100]
write("customer_inventory.json", cust)
tg = []
for r in cust:
    for p in r["prefixes"]:
        n = ipaddress.ip_network(p)
        for s in ([n] if n.prefixlen >= 24 else list(n.subnets(new_prefix=24))[:4]):
            h = next(s.hosts(), None)
            if h:
                tg.append(str(h))
write("customer_targets.txt", "\n".join(sorted(set(tg), key=lambda s: ipaddress.ip_address(s))) + "\n")

# ---- PeeringDB: IX ports, facilities ----------------------------------------
ix_ports, facs = [], []
for a in ASNS:
    pdb = get(f"https://www.peeringdb.com/api/net?asn={a}&depth=2").get("data", [])
    if not pdb:
        continue
    net = pdb[0]
    lans = get(f"https://www.peeringdb.com/api/netixlan?net_id={net['id']}").get("data", [])
    ixids = sorted({x["ix_id"] for x in lans})
    ixs = {x["id"]: x for x in get("https://www.peeringdb.com/api/ix?id__in=" + ",".join(map(str, ixids))).get("data", [])} if ixids else {}
    he = get("https://www.peeringdb.com/api/netixlan?asn=6939&ix_id__in=" + ",".join(map(str, ixids))).get("data", []) if ixids else []
    for x in lans:
        ix_ports.append({"ix": x["name"], "ix_id": x["ix_id"], "city": ixs.get(x["ix_id"], {}).get("city"), "local_ip": x["ipaddr4"],
                         "speed_mbps": x["speed"], "rs_peer": x["is_rs_peer"], "participants": ixs.get(x["ix_id"], {}).get("net_count"),
                         "he_ips": [y["ipaddr4"] for y in he if y["ix_id"] == x["ix_id"]], "source": "PeeringDB netixlan"})
    fids = [f["fac_id"] for f in net.get("netfac_set", [])]
    if fids:
        facs += [{"name": f["name"], "city": f["city"], "state": f.get("state")} for f in
                 get("https://www.peeringdb.com/api/fac?id__in=" + ",".join(map(str, fids))).get("data", [])]
write("ix_ports.json", [x for x in ix_ports if x["local_ip"]])
write("facilities.json", facs)

cfg = NET / "config.json"
if not cfg.exists():
    name = stat(f"as-overview/data.json?resource=AS{ASNS[0]}").get("holder", f"AS{ASNS[0]}")
    cfg.write_text(json.dumps({"asn": ASNS[0], "asns": ASNS, "name": name, "loopbacks": [], "pins": {}, "placement": {"near_ms": 1.5, "metro_to_pop": {}, "regional": {}},
                               "transit": {}, "ix_metro": {}, "pops": {}, "region_order": []}, indent=1) + "\n", newline="\n")
print(f"{len(prefixes)} prefixes, {len(probe)} /24 probes, {len(cust)} customer ASes ({len(tg)} targets), "
      f"{len(ix_ports)} IX ports, {len(facs)} facilities -> {RAW}")
if dropped:
    print("dropped as probable leak/artefact (more than 100 prefixes):", dropped)
print("Add IX ports that only bgp.he.net lists (its IX tab) to raw/ix_ports.json by hand, with source='bgp.he.net'.")
