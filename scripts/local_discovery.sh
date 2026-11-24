#!/bin/sh
# Stage 2 (local machine, free, no rate limits): router-level discovery of one network.
# Needs: scamper, fping, python3   (Ubuntu/WSL: sudo apt install scamper fping python3)
# Run as root (raw sockets):  sudo sh local_discovery.sh <net-dir> [pps]
#
# Reads <net>/raw/prefixes.txt, probe24.txt, customer_targets.txt (from bootstrap.py) and <net>/config.json.
# Makes no DNS or web lookups, so it can run from any connection (see field-run notes in SKILL.md).
# Writes <net>/raw/local/<date>/ and a .tgz of it. Then run ingest_local.py.
# Phases: preflight; A trace each /24; B sweep router /24s + loopback blocks; C trace every live address;
#         D alias resolution (mercator, radargun); E link mates (prefixscan); F trace customer targets.
set -eu

NET=$(cd "${1:?usage: sudo sh local_discovery.sh <net-dir> [pps]}" && pwd)
PPS=${2:-100}
S=$(cd "$(dirname "$0")" && pwd)
OUT="$NET/raw/local/$(date +%Y%m%d-%H%M)"
H="python3 $S/helpers.py"
P="$NET/raw/prefixes.txt"
mkdir -p "$OUT"; cd "$OUT"
log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a run.log; }
j() { sc_warts2json "$1" > "${1%.warts}.json"; }

for t in scamper sc_warts2json sc_radargun sc_prefixscan fping python3; do
  command -v $t >/dev/null || { echo "missing: $t (sudo apt install scamper fping python3)"; exit 1; }
done
[ "$(id -u)" = 0 ] || { echo "run with sudo: scamper needs raw sockets"; exit 1; }

log "preflight: traceroute to 8.8.8.8 and a UDP probe into the target"
scamper -c 'trace -P icmp-paris -q 1 -w 2' -i 8.8.8.8 -O warts -o pre_trace.warts 2>/dev/null; j pre_trace.warts
HOPS=$(python3 -c "import json;d=[json.loads(l) for l in open('pre_trace.json') if '\"trace\"' in l][0];print(len({h['addr'] for h in d.get('hops',[])}))")
scamper -c 'dealias -m mercator -q 2' -i "$(head -1 "$NET/raw/probe24.txt")" -O warts -o pre_merc.warts 2>/dev/null; j pre_merc.warts
UDP=$(grep -c '"icmp_type":3' pre_merc.json || true)
log "preflight: $HOPS responding hops to 8.8.8.8; UDP port-unreachable replies: $UDP"
[ "$HOPS" -ge 4 ] || { log "STOP: this connection hides traceroute hops. Results would be empty."; exit 2; }
[ "$UDP" -gt 0 ] || log "warning: no UDP replies; mercator will find nothing (radargun and prefixscan still run)"

log "A: tracing $(wc -l < "$NET/raw/probe24.txt") /24 targets at $PPS pps"
scamper -p "$PPS" -c 'trace -P icmp-paris -q 1 -w 2 -g 6' -f "$NET/raw/probe24.txt" -O warts -o a_traces.warts 2>/dev/null; j a_traces.warts
$H hops a_traces.json "$P" . | tee -a run.log

$H expand infra24.txt > sweep.txt
$H loopbacks "$NET/config.json" >> sweep.txt
sort -u sweep.txt -o sweep.txt
log "B: sweeping $(wc -l < sweep.txt) addresses (router /24s + configured loopback blocks)"
fping -a -q -r 1 -i 10 -f sweep.txt > alive.txt 2>/dev/null || true
log "B: $(wc -l < alive.txt) live"

log "C: tracing every live address"
scamper -p "$PPS" -c 'trace -P icmp-paris -q 1 -w 2 -g 6' -f alive.txt -O warts -o c_traces.warts 2>/dev/null; j c_traces.warts
$H hops c_traces.json "$P" . | tee -a run.log
$H lbloc "$NET/config.json" lbloc.json a_traces.json c_traces.json | tee -a run.log

$H cands . 600 | tee -a run.log
log "D: mercator"
scamper -p "$PPS" -c 'dealias -m mercator -q 2' -f cands.txt -O warts -o merc.warts 2>/dev/null; j merc.warts
log "D: radargun (30 rounds x 15 s, about 8 minutes)"
scamper -P 31337 -p 60 -D 2>/dev/null; sleep 2
sc_radargun -a cands.txt -o rg.warts -p 31337 -P 60 -r 15 -R 30 >> run.log 2>&1 || true
sc_radargun -d 1 rg.warts > rg_aliases.txt 2>/dev/null || true
sc_radargun -d 2 rg.warts > rg_class.txt 2>/dev/null || true

$H pairs a_traces.json c_traces.json "$P" pairs.txt | tee -a run.log
log "E: prefixscan"
sc_prefixscan -i pairs.txt -o ps.warts -p 31337 -x 30 -w 1 >> run.log 2>&1 || true
sc_prefixscan -r ps.warts -x 30 > ps_out.txt 2>/dev/null || true
pkill -f 'scamper -P 31337' || true

if [ -s "$NET/raw/customer_targets.txt" ]; then
  log "F: tracing $(wc -l < "$NET/raw/customer_targets.txt") customer targets"
  scamper -p "$PPS" -c 'trace -P icmp-paris -q 2 -w 2 -g 8' -f "$NET/raw/customer_targets.txt" -O warts -o f_customers.warts 2>/dev/null; j f_customers.warts
fi

log "done: $OUT"
$H summary . | tee -a run.log
cd .. && tar czf "$(basename "$OUT").tgz" "$(basename "$OUT")" && log "archive: $NET/raw/local/$(basename "$OUT").tgz"
