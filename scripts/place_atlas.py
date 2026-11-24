"""Stage 4b (RIPE Atlas: needs an API key with credits): ping or traceroute from many probes, throttled.

usage: python place_atlas.py <net-dir> ping   <probe-ids-file|metro-json> [--targets file] [--inflight 5]
       python place_atlas.py <net-dir> fetch                           (collect results into placement.json)

Key: env RIPE_ATLAS_KEY (on Windows the User env var is read too).
probe-ids-file: one probe id per line, or a JSON {metro: [probe ids]} so results are keyed by metro.
Targets default to one loopback + one other interface per router in <net>/topology.json.

Lessons that shaped this script:
- Never send hundreds of one-offs to the same few probes. A probe runs only a few of your
  measurements at a time; the rest sit "Scheduled" and then fail. Keep --inflight small (5-10).
- One-offs fail platform-wide at times (in Nov 2026, 97 of 100 public one-offs in an hour failed).
  Before blaming your setup, list recent public measurements' status (see SKILL.md).
"""
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
MODE = sys.argv[2]
RAW = NET / "raw"
args = sys.argv[3:]
key = os.environ.get("RIPE_ATLAS_KEY") or (subprocess.run(["powershell", "-NoProfile", "-Command",
      "[Environment]::GetEnvironmentVariable('RIPE_ATLAS_KEY','User')"], capture_output=True, text=True).stdout.strip()
      if os.name == "nt" else "")
H = {"Authorization": "Key " + key, "Content-Type": "application/json"}
API = "https://atlas.ripe.net/api/v2/measurements/"
STATE = RAW / "atlas_state.json"
state = json.loads(STATE.read_text()) if STATE.exists() else {"msm": {}, "probe_metro": {}}
DONE = {"Stopped", "Failed", "Forced to stop", "No suitable probes", "Denied", "Canceled", "Cancelled", "Archived"}


def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60))


if MODE == "ping":
    src = args[0]
    if src.endswith(".json"):
        pm = json.loads(open(src).read())
        ids = sorted({p for v in pm.values() for p in v})
        state["probe_metro"].update({str(p): m for m, v in pm.items() for p in v})
    else:
        ids = [int(l) for l in open(src) if l.strip()]
    if "--targets" in args:
        targets = [l.strip() for l in open(args[args.index("--targets") + 1]) if l.strip()]
    else:
        topo = json.loads((NET / "topology.json").read_text())
        targets = [x for r in topo["routers"] for x in [r["loopback"]] + [i for i in r["interfaces"] if i != r["loopback"]][:1]]
    n = int(args[args.index("--inflight") + 1]) if "--inflight" in args else 5
    q = [t for t in targets if t not in state["msm"]]
    inflight = {}
    while q or inflight:
        while q and len(inflight) < n:
            body = {"definitions": [{"type": "ping", "af": 4, "target": q[0], "packets": 3, "description": "netmap placement", "is_public": True}],
                    "probes": [{"requested": len(ids), "type": "probes", "value": ",".join(map(str, ids))}], "is_oneoff": True}
            try:
                m = json.load(urllib.request.urlopen(urllib.request.Request(API, json.dumps(body).encode(), H), timeout=60))["measurements"][0]
                inflight[q.pop(0)] = m
            except urllib.error.HTTPError:
                time.sleep(20); break
        time.sleep(20)
        for t, m in list(inflight.items()):
            s = get(f"{API}{m}/")["status"]["name"]
            if s in DONE:
                state["msm"][t] = {"id": m, "status": s}; del inflight[t]
        STATE.write_text(json.dumps(state, indent=1) + "\n", newline="\n")
        print(f"done {len(state['msm'])} inflight {len(inflight)} queued {len(q)}", flush=True)
    MODE = "fetch"

if MODE == "fetch":
    pf = RAW / "placement.json"
    place = json.loads(pf.read_text()) if pf.exists() else {}
    for t, v in state["msm"].items():
        for r in get(f"{API}{v['id']}/results/"):
            if r.get("min") and r["min"] > 0:
                metro = state["probe_metro"].get(str(r["prb_id"]), f"probe{r['prb_id']}")
                place.setdefault(t, {})[metro] = min(round(r["min"], 1), place.get(t, {}).get(metro, 1e9))
    pf.write_text(json.dumps(place, indent=1, sort_keys=True) + "\n", newline="\n")
    print(f"placement.json: {len(place)} addresses with probe RTTs")
