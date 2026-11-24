"""Stage 3 (offline): copy a local discovery run into the files build_topology.py reads.

usage: python ingest_local.py <net-dir> [run-dir]     (default: newest <net>/raw/local/*/)

Writes <net>/raw/: ps_out.txt, rg_aliases.txt, alive.txt, lbloc.json, local_rtt.json, customer_paths.json.
local_rtt.json is {ip: min RTT from the local machine}; it is a check on placements, not a location.
customer_paths.json is [{vp, dst, hops: [ip|null, ...]}] for customer_attach.py.
Existing extra files (rg_aliases_*.txt, placement.json, labels.json ...) are left alone.
"""
import json, pathlib, shutil, sys

NET = pathlib.Path(sys.argv[1]).resolve()
RAW = NET / "raw"
runs = sorted(p for p in (RAW / "local").glob("*") if p.is_dir())
RUN = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else runs[-1]

for src, dst in (("ps_out.txt", "ps_out.txt"), ("rg_aliases.txt", "rg_aliases.txt"), ("alive.txt", "alive.txt"), ("lbloc.json", "lbloc.json")):
    if (RUN / src).exists():
        shutil.copyfile(RUN / src, RAW / dst)


def traces(path):
    for line in open(path):
        d = json.loads(line)
        if d.get("type") == "trace":
            yield d


rtt = {}
for f in ("a_traces.json", "c_traces.json"):
    if (RUN / f).exists():
        for d in traces(RUN / f):
            for h in d.get("hops", []):
                if "rtt" in h:
                    rtt[h["addr"]] = round(min(h["rtt"], rtt.get(h["addr"], 1e9)), 1)
(RAW / "local_rtt.json").write_text(json.dumps(dict(sorted(rtt.items())), indent=1) + "\n", newline="\n")

paths = []
if (RUN / "f_customers.json").exists():
    for d in traces(RUN / "f_customers.json"):
        hops = {}
        for h in d.get("hops", []):
            hops.setdefault(h["probe_ttl"], h["addr"])
        paths.append({"vp": "local", "dst": d["dst"], "hops": [hops.get(t) for t in range(1, max(hops, default=0) + 1)]})
(RAW / "customer_paths.json").write_text(json.dumps(paths) + "\n", newline="\n")
print(f"ingested {RUN.name}: {len(rtt)} hop RTTs, {len(paths)} customer paths")
