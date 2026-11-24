"""usage: python build_customers.py <net-dir>

Build raw/customers.json: each downstream customer AS and the operator router(s) it attaches to.

Inputs (raw/):
  customer_inventory.json  RIPEstat: ASNs listing the target AS as an upstream, their prefixes and other upstreams
  customer_traces.json     per ASN, one row per traceroute (local scamper + external probes):
                           vp, dst, attach (router id or None), opi_if, next (first hop after the operator)

Run customer_attach.py first; then rerun build_topology.py, which merges customers.json into topology.json.
"""
import json, collections, pathlib

import sys
NET = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
RAW = NET / "raw"
_cfg = json.loads((NET / "config.json").read_text())
FAMILY = set(_cfg.get("asns", [_cfg["asn"]]))
inv = json.loads((RAW / "customer_inventory.json").read_text())
rows = json.loads((RAW / "customer_traces.json").read_text())
# router interfaces from the previous build, to recognise a handoff by its /31-/30 partner
_topo = NET / "topology.json"
OWNER = {i: r["id"] for r in json.loads(_topo.read_text())["routers"] for i in r["interfaces"]} if _topo.exists() else {}


def mates(ip):
    import ipaddress
    n = int(ipaddress.ip_address(ip))
    out = [n ^ 1] + ([n + 1 if n % 4 == 1 else n - 1] if n % 4 in (1, 2) else [])
    return [str(ipaddress.ip_address(x)) for x in out]

out = []
for c in sorted((c for c in inv if c["asn"] not in FAMILY), key=lambda c: c["asn"]):
    rs = rows.get(str(c["asn"]), [])
    # One customer edge address is one physical handoff. If traces reach the same edge through different
    # "last seen" routers, the minority ones are paths where the true attachment router was hidden (MPLS),
    # so attribute every trace to the router most often seen before that edge. Distinct edges (a customer
    # with two handoffs) keep their own routers.
    per_edge = collections.defaultdict(collections.Counter)
    for r in rs:
        if r.get("attach") and r.get("next") and not r["attach"].startswith(("opi-space", "own-space")):
            per_edge[r["next"]][r["attach"]] += 1
    major = {e: c_.most_common(1)[0][0] for e, c_ in per_edge.items()}
    for e in per_edge:  # strongest evidence: the edge's /31-/30 partner is a known interface of a router
        mate = next((OWNER[m] for m in mates(e) if m in OWNER), None)
        if mate:
            major[e] = mate
    att = collections.defaultdict(lambda: {"traces": 0, "vps": set(), "edge": collections.Counter()})
    for r in rs:
        a = major.get(r.get("next"), r.get("attach"))
        if a and not a.startswith(("opi-space", "own-space")):
            att[a]["traces"] += 1
            att[a]["vps"].add(r["vp"])
            if r.get("next"):
                att[a]["edge"][r["next"]] += 1
    bypass = sorted({r["vp"] for r in rs if not r.get("attach")} - {r["vp"] for r in rs if r.get("attach")})
    edge = collections.Counter()
    for a in att.values():
        edge.update(a["edge"])
    out.append({
        "asn": c["asn"],
        "name": c["holder"],
        "prefixes": len(c["prefixes"]),
        "other_upstreams": sorted(u for u, _ in c["upstreams"] if u not in FAMILY),
        # drop stray paths: fewer than 3 traces and under 5% of the customer's attached traces
        "attach": [{"router": k, "traces": v["traces"], "vantage_points": sorted(v["vps"]),
                    "evidence": f"{v['traces']} traces from {len(v['vps'])} vantage point{'s' if len(v['vps']) != 1 else ''}"}
                   for k, v in sorted(att.items(), key=lambda kv: (-kv[1]["traces"], kv[0]))
                   if v["traces"] >= 3 or v["traces"] >= 0.05 * sum(x["traces"] for x in att.values())],
        "edge": [e for e, _ in sorted(edge.items(), key=lambda kv: (-kv[1], kv[0]))[:3]],
        "never_via_operator_from": bypass,
        "traces": len(rs),
    })
(RAW / "customers.json").write_text(json.dumps(out, indent=1) + "\n", newline="\n")
print(f"{len(out)} customers -> raw/customers.json; {sum(1 for c in out if c['attach'])} with an attachment router")
