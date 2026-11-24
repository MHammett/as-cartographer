"""Stage 1b (free APIs): propose sibling ASNs, the other ASNs one company's network is built from.

usage: python family.py <net-dir> AS<seed> [--names "word,word"]

Evidence, strongest first:
  registry-org   the RIR lists the ASN under the same organisation as the seed (RDAP)
  peeringdb-org  PeeringDB lists the network under the same organisation as the seed
  shared-space   the neighbour originates, or once originated, address space registered to the seed's organisation
  history-origin the ASN once originated one of the seed's prefixes (absorbed or predecessor network)
  name           AS name or holder contains one of --names (former brands, acquired companies)
Writes <net>/raw/family_candidates.json and prints a suggested config.json "asns" list.
Nothing is added automatically: siblings change the customer list and the map, so confirm with the user.
"""
import collections, json, pathlib, sys, time, urllib.parse, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
SEED = int(sys.argv[2].upper().lstrip("AS"))
NAMES = [w.strip().lower() for w in (sys.argv[sys.argv.index("--names") + 1].split(",") if "--names" in sys.argv else []) if w.strip()]
RAW = NET / "raw"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "as-cartographer", "Accept": "application/rdap+json, application/json"}


def get(u, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
        except Exception:
            time.sleep(3 * (i + 1))  # PeeringDB throttles anonymous clients
    return {}


def stat(p):
    return get("https://stat.ripe.net/data/" + p).get("data", {})


ev = collections.defaultdict(set)
holder = {}

# registry organisation (rdap.org redirects to the right RIR)
auto = get(f"https://rdap.org/autnum/{SEED}")
orgs = [e["handle"] for e in auto.get("entities", []) if "registrant" in (e.get("roles") or [])]
org_nets = []
for h in orgs:
    ent = get(f"https://rdap.org/entity/{urllib.parse.quote(h)}")
    for a in ent.get("autnums", []):
        for n in range(int(a.get("startAutnum", 0)), int(a.get("endAutnum", a.get("startAutnum", 0))) + 1):
            if n != SEED:
                ev[n].add(f"registry-org {h}")
    org_nets += [f"{x.get('startAddress')}-{x.get('endAddress')}" for x in ent.get("networks", [])]

# PeeringDB organisation
pdb = get(f"https://www.peeringdb.com/api/net?asn={SEED}").get("data", [])
if pdb:
    for x in get(f"https://www.peeringdb.com/api/net?org_id={pdb[0]['org_id']}").get("data", []):
        if x["asn"] != SEED:
            ev[x["asn"]].add(f"peeringdb-org {pdb[0]['org_id']}")

# neighbours originating space registered to the seed's org, now or historically
nbrs = {x["asn"] for x in stat(f"asn-neighbours/data.json?resource=AS{SEED}").get("neighbours", [])}
seed_prefixes = [p["prefix"] for p in stat(f"announced-prefixes/data.json?resource=AS{SEED}").get("prefixes", [])]
for p in seed_prefixes:
    for o in stat(f"routing-history/data.json?resource={p}&min_peers=3").get("by_origin", []):
        asn = int(o["origin"])
        if asn != SEED and any(pf["prefix"] == p or pf["prefix"].startswith(p.split("/")[0].rsplit(".", 1)[0]) for pf in o.get("prefixes", [])):
            first = min((t["starttime"] for pf in o.get("prefixes", []) for t in pf.get("timelines", [])), default="")[:10]
            ev[asn].add(f"history-origin {p} since {first}")

# names
if NAMES:
    for w in NAMES:
        for cat in stat(f"searchcomplete/data.json?resource={urllib.parse.quote(w)}").get("categories", []):
            if cat["category"] == "ASNs":
                for s in cat["suggestions"]:
                    n = int(s["value"].lstrip("AS"))
                    if n != SEED:
                        ev[n].add(f"name '{w}'")
    for n in nbrs:
        h = stat(f"as-overview/data.json?resource=AS{n}").get("holder", "")
        holder[n] = h
        if any(w in h.lower() for w in NAMES):
            ev[n].add("name (neighbour)")

rows = []
for n, e in ev.items():
    h = holder.get(n) or stat(f"as-overview/data.json?resource=AS{n}").get("holder", "")
    ann = stat(f"announced-prefixes/data.json?resource=AS{n}").get("prefixes", [])
    rows.append({"asn": n, "holder": h, "neighbour_of_seed": n in nbrs, "announces": len(ann), "evidence": sorted(e)})
strength = {"registry-org": 3, "peeringdb-org": 3, "shared-space": 2, "history-origin": 1, "name": 1, "provider-of-space": 0}
# A large network (transit provider, address-space holder) that once originated the seed's space assigned it
# out; it is a former provider, not a sibling. Flag instead of drop: it still explains where the space came from.
for r in rows:
    if r["announces"] > 200:
        r["evidence"] = [("provider-of-space " + x[len("history-origin "):]) if x.startswith("history-origin") else x for x in r["evidence"]]
rows.sort(key=lambda r: (-max(strength.get(x.split()[0], 0) for x in r["evidence"]), -len(r["evidence"]), r["asn"]))
(RAW / "family_candidates.json").write_text(json.dumps(rows, indent=1) + "\n", newline="\n")
print(f"seed AS{SEED}; registry org {orgs}; {len(rows)} candidates")
# a name match alone, on an ASN that is not even a BGP neighbour, is almost always an unrelated namesake
shown = [r for r in rows if r["neighbour_of_seed"] or any(not x.startswith("name") for x in r["evidence"])]
print(f"  ({len(rows) - len(shown)} name-only matches that are not neighbours hidden; see family_candidates.json)")
for r in shown:
    print(f"  AS{r['asn']:<7} {r['holder'][:40]:40s} announces {r['announces']:4d}  {'neighbour ' if r['neighbour_of_seed'] else ''}{'; '.join(r['evidence'])}")
strong = [r["asn"] for r in rows if any(x.split()[0] in ("registry-org", "peeringdb-org") for x in r["evidence"]) and r["announces"]]
print("suggested config.json \"asns\":", [SEED] + strong, " (add others only after checking them)")
