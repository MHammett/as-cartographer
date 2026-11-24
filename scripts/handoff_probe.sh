#!/bin/sh
# Local probe for handoffs.py (free, no rate limits): min RTT to each customer edge, its /31-/30 partners and the
# attach router, plus IP-ID alias rows [edge, mates..., router loopback] to find which side is the operator's.
# usage: sudo sh handoff_probe.sh <net-dir>      (after: python handoffs.py <net-dir> plan)
set -eu
NET=$(cd "${1:?usage: sudo sh handoff_probe.sh <net-dir>}" && pwd)
OUT="$NET/raw/handoff_probe"; mkdir -p "$OUT"; cd "$OUT"
scamper -p 50 -c 'ping -c 30 -i 0.5' -f "$NET/raw/handoff_targets.txt" -O warts -o pings.warts 2>/dev/null
sc_warts2json pings.warts > pings.json
python3 - <<'PY'
import json
rtt = {}
for line in open("pings.json"):
    d = json.loads(line)
    if d.get("type") == "ping":
        r = [x["rtt"] for x in d.get("responses", []) if "rtt" in x]
        if r:
            rtt[d["dst"]] = round(min(r), 2)
json.dump(rtt, open("rtt.json", "w"), indent=1)
print(len(rtt), "addresses answered")
PY
scamper -P 31342 -p 40 -D 2>/dev/null; sleep 2
sc_radargun -a "$NET/raw/handoff_rows.txt" -O rows -o rg.warts -p 31342 -P 40 -r 5 -R 30 > rg.log 2>&1 || true
sc_radargun -d 1 rg.warts > al.txt 2>/dev/null || true
sc_radargun -d 2 rg.warts > cls.txt 2>/dev/null || true
pkill -f 'scamper -P 31342' || true
echo "done: $OUT"
