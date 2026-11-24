"""Stage 4a (free, no account): place routers by pinging them from Globalping probes in named cities.

usage: python place_globalping.py <net-dir> "Chicago,Dallas,Denver,..." [--targets file] [--per-city 2]

Targets default to one loopback plus one other interface per router in <net>/topology.json (run
build_topology.py once first), or pass --targets with one IP per line. Results merge into
<net>/raw/placement.json as {ip: {city: min_rtt_ms}}, keyed by the city name you asked for.
Map city names to PoP codes in config.json placement.metro_to_pop.

Budget: Globalping allows 250 tests/hour per IP without a token (each probe in a measurement is one
test). This script stops before the budget runs out, saves what it has, and resumes skipping
finished (target, city) pairs when rerun. Set GLOBALPING_TOKEN for 500/hour.
API: https://api.globalping.io/v1/spec.yaml
"""
import json, os, pathlib, sys, time, urllib.error, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
CITIES = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
args = sys.argv[3:]
per_city = int(args[args.index("--per-city") + 1]) if "--per-city" in args else 2  # one probe can sit on an ISP that routes the long way
API = "https://api.globalping.io/v1/measurements"
HDR = {"Content-Type": "application/json", "User-Agent": "as-cartographer"}
if os.environ.get("GLOBALPING_TOKEN"):
    HDR["Authorization"] = "Bearer " + os.environ["GLOBALPING_TOKEN"]

if "--targets" in args:
    targets = [l.strip() for l in open(args[args.index("--targets") + 1]) if l.strip()]
else:
    topo = json.loads((NET / "topology.json").read_text())
    targets = []
    for r in topo["routers"]:
        targets.append(r["loopback"])
        other = [i for i in r["interfaces"] if i != r["loopback"]]
        if other:
            targets.append(other[0])

pf = NET / "raw" / "placement.json"
place = json.loads(pf.read_text()) if pf.exists() else {}
done_f = NET / "raw" / "globalping_done.json"
done = set(map(tuple, json.loads(done_f.read_text()))) if done_f.exists() else set()


def call(url, body=None):
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None, HDR)
    return json.load(urllib.request.urlopen(req, timeout=60))


budget_left = None
for t in targets:
    todo = [c for c in CITIES if (t, c) not in done]
    if not todo:
        continue
    if budget_left is not None and budget_left < len(todo) * per_city:
        print("hourly Globalping budget nearly used; rerun later to continue"); break
    body = {"type": "ping", "target": t, "measurementOptions": {"packets": 3},
            "locations": [{"magic": c, "limit": per_city} for c in todo]}
    try:
        req = urllib.request.Request(API, json.dumps(body).encode(), HDR)
        resp = urllib.request.urlopen(req, timeout=60)
        budget_left = int(resp.headers.get("X-RateLimit-Remaining", 999))
        mid = json.load(resp)["id"]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("rate limited (429); rerun later to continue"); break
        print(t, "error", e.code, e.read()[:200]); continue
    for _ in range(30):
        time.sleep(2)
        m = call(f"{API}/{mid}")
        if m.get("status") != "in-progress":
            break
    for r in m.get("results", []):
        loc = r["probe"]
        city = next((c for c in todo if c.lower() in (loc.get("city") or "").lower()), loc.get("city"))
        st = r.get("result", {}).get("stats", {}) or {}
        if st.get("min") is not None:
            place.setdefault(t, {})[city] = min(round(st["min"], 1), place.get(t, {}).get(city, 1e9))
    done.update((t, c) for c in todo)
    pf.write_text(json.dumps(place, indent=1, sort_keys=True) + "\n", newline="\n")
    done_f.write_text(json.dumps(sorted(done)) + "\n", newline="\n")
    best = sorted(place.get(t, {}).items(), key=lambda kv: kv[1])[:3]
    print(f"{t:16s} {'  '.join(f'{c} {v}' for c, v in best) or 'no replies'}   (budget left {budget_left})")
