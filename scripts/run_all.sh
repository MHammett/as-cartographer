#!/bin/sh
# Every stage that needs no judgment, in cost order, with no Claude involvement (no tokens).
# usage: sh run_all.sh <net-dir> AS<n> [AS<n> ...]
#   - on Windows, run from WSL as root: wsl -u root -e sh run_all.sh /mnt/c/.../<net-dir> AS64500
#   - needs: python3 (with network access), scamper, fping, graphviz; run as root for raw sockets
# The judgment points are left out, deliberately. Do them between runs, then rerun from "build":
#   which ASNs are one company (family.py), config.json pins / placement rules / PoP names, looking
#   glasses (browser; some need a person), history findings turned into tests, extra_evidence.json.
set -eu
NET=${1:?usage: sh run_all.sh <net-dir> AS<n> [AS<n> ...]}; shift
S=$(cd "$(dirname "$0")" && pwd)
PY=python3
step() { printf '\n== %s  %s\n' "$(date +%H:%M:%S)" "$*"; }

step "1 bootstrap (RIPEstat, PeeringDB)";  $PY "$S/bootstrap.py" "$NET" "$@"
step "2 local discovery (scamper)";        sh "$S/local_discovery.sh" "$NET"
step "3 ingest + build";                   $PY "$S/ingest_local.py" "$NET"; $PY "$S/build_topology.py" "$NET"
step "4 customers";                        $PY "$S/customer_attach.py" "$NET"; $PY "$S/build_customers.py" "$NET"; $PY "$S/build_topology.py" "$NET"
step "5 reverse DNS";                      $PY "$S/rdns.py" "$NET"; $PY "$S/build_topology.py" "$NET"
step "6 handoffs (local probe + RIS)";     $PY "$S/handoffs.py" "$NET" plan; sh "$S/handoff_probe.sh" "$NET"; $PY "$S/handoffs.py" "$NET" report
step "7 history (hypotheses to test)";     $PY "$S/history.py" "$NET" || true
step "8 render";                           $PY "$S/render.py" "$NET"
echo
echo "Done. Next, the judgment steps (see SKILL.md): placement (place_globalping.py / place_atlas.py),"
echo "config.json pins and PoP names, looking glasses, testing the history hypotheses printed above."
