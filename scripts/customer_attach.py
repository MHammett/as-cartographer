"""Stage 5 (offline): where does each downstream customer attach?   usage: python customer_attach.py <net-dir>

Reads <net>/raw/customer_paths*.json ([{vp, dst, hops}] from ingest_local.py, plus any external traces you
convert to the same shape, e.g. customer_paths_atlas.json), customer_inventory.json and topology.json.
Writes raw/customer_traces.json for build_customers.py.

Attachment = the last hop that is a known router interface; the customer edge = the next responding hop.
Lesson: the hop just past the operator is often the CUSTOMER's end of an operator-numbered /30. It looks like
an operator router (it is in the operator's space) but it is not one; only alias-resolved interfaces count.
"""
import ipaddress, json, pathlib, sys

NET = pathlib.Path(sys.argv[1]).resolve()
RAW = NET / "raw"
topo = json.loads((NET / "topology.json").read_text())
owner = {i: r["id"] for r in topo["routers"] for i in r["interfaces"]}
own_nets = [ipaddress.ip_network(l.strip()) for l in open(RAW / "prefixes.txt") if l.strip()]
inv = json.loads((RAW / "customer_inventory.json").read_text())
cnets = sorted(((ipaddress.ip_network(p), c["asn"]) for c in inv for p in c["prefixes"]), key=lambda t: -t[0].prefixlen)


def asn_of(ip):
    a = ipaddress.ip_address(ip)
    return next((asn for n, asn in cnets if a in n), None)


def in_own(ip):
    a = ipaddress.ip_address(ip)
    return any(a in n for n in own_nets)


rows = {}
for f in sorted(RAW.glob("customer_paths*.json")):
    for p in json.loads(f.read_text()):
        hl, asn = p["hops"], asn_of(p["dst"])
        last = next((i for i in range(len(hl) - 1, -1, -1) if hl[i] in owner), None)
        if last is None:
            last = next((i for i in range(len(hl) - 1, -1, -1) if hl[i] and in_own(hl[i])), None)
        att = owner.get(hl[last], f"own-space {hl[last]}") if last is not None else None
        nxt = next((x for x in hl[last + 1:] if x), None) if last is not None else None
        rows.setdefault(str(asn), []).append({"vp": p["vp"], "dst": p["dst"], "attach": att, "next": nxt})
(RAW / "customer_traces.json").write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", newline="\n")
for asn, rs in sorted(rows.items()):
    hit = sorted({r["attach"] for r in rs if r["attach"]})
    print(f"AS{asn:<8} {len(rs):4d} traces  attach: {', '.join(hit) or 'never crossed the operator from these vantage points'}")
