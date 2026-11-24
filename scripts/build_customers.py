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

out = []
for c in sorted((c for c in inv if c["asn"] not in FAMILY), key=lambda c: c["asn"]):
    rs = rows.get(str(c["asn"]), [])
    att = collections.defaultdict(lambda: {"traces": 0, "vps": set(), "edge": collections.Counter()})
    for r in rs:
        a = r.get("attach")
        if a and not a.startswith("opi-space"):
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
        "attach": [{"router": k, "traces": v["traces"], "vantage_points": sorted(v["vps"]),
                    "evidence": f"{v['traces']} traces from {len(v['vps'])} vantage point{'s' if len(v['vps']) != 1 else ''}"}
                   for k, v in sorted(att.items(), key=lambda kv: (-kv[1]["traces"], kv[0]))],
        "edge": [e for e, _ in sorted(edge.items(), key=lambda kv: (-kv[1], kv[0]))[:3]],
        "never_via_operator_from": bypass,
        "traces": len(rs),
    })
(RAW / "customers.json").write_text(json.dumps(out, indent=1) + "\n", newline="\n")
print(f"{len(out)} customers -> raw/customers.json; {sum(1 for c in out if c['attach'])} with an attachment router")
