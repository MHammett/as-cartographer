---
name: as-cartographer
description: Map another operator's network (an ASN) at router level from outside, cheapest sources first. Covers the local scamper pipeline (traceroute, IP-ID alias resolution, /31-/30 link mates), free APIs (RIPEstat, PeeringDB, reverse DNS, Globalping), RIPE Atlas, looking glasses, BGP communities, customer attachment and history. Ends in a deterministic map (Graphviz SVG/PDF/PNG and a native Visio .vsdx). Use when asked to map, verify or reverse-engineer an ISP's PoPs, routers, links, upstreams, IX ports or customers, or to check what an operator claims about its network.
---

# Router-level map of a network, from outside

A method for mapping another operator's network from outside. It is ordered by cost. Each stage
fills gaps the previous one left, so stop when the question is answered.

| Stage | Source | Cost and limits | What it gives |
|---|---|---|---|
| 1 | Free APIs: RDAP, RIPEstat, PeeringDB | free, about 50-100 calls | sibling ASNs, prefixes, neighbours, customers, IX ports with speed, facilities |
| 2 | **Local scamper** (`local_discovery.sh`) | free, no rate limit; about 30-60 min at 100 pps | routers (alias resolution), links (/31-/30 mates), loopback IDs, customer attachment |
| 3 | Offline build | free | `topology.json` and the maps |
| 4a | Reverse DNS (DoH), Globalping | free; Globalping 250 tests/hour without a token | names of transit handoffs; router locations by city |
| 4b | RIPE Atlas | credits; flaky one-offs; throttle | dense placement; vantage points inside other networks |
| 5 | Looking glasses (HE, the transit provider's) | rate limits; some need a human for a CAPTCHA | where sessions are, transit-provider router names, BGP communities |
| 6 | History: RIPEstat history, others' Atlas traces, Wayback | free but slow | hypotheses (old links, PoPs, absorbed networks) to retest with stage 2 tools |

Before starting, ask what the user wants answered. Usually that is "is X connected to Y, and how". A partial
map from stages 1-3 often answers it.

**Spend tokens only on judgment.** `scripts/run_all.sh <net> AS<n> ...` runs every stage that needs no
decisions, unattended:
- bootstrap,
- local discovery,
- build,
- customers,
- reverse DNS,
- handoffs,
- history,
- render.

Start it in the background and wait for it to finish. It takes about 45-75 minutes, mostly local probing.
Claude's work is the judgment in between:
- which ASNs form the family,
- `config.json` pins and PoP names,
- placement runs,
- looking glasses,
- turning history into tests,
- recording `extra_evidence.json`.

After any judgment step, rerun from build (`build_topology.py` then `render.py`), not the whole pipeline.

**Ground truth from the user beats inference.** If the user knows where something is ("DynaCom is in
Naperville", "Express Dial has a microwave link to Big Rock"), test the network against it and then pin
it in `config.json` with a label saying the location came from the user.

## Setup (once per machine)

- Python 3 on the host.
- Scamper, fping and Graphviz on Linux, or in WSL on Windows: `sudo apt install scamper fping python3 graphviz`. On Windows, run the shell
  scripts with `wsl -u root -e sh <script>`; from Git Bash, set `MSYS_NO_PATHCONV=1` so `/mnt/c/...` paths
  are not rewritten.
- For Visio output only: Visio and `pip install pywin32`.
- For stage 4b only: a RIPE Atlas API key in env `RIPE_ATLAS_KEY` with "schedule a new measurement"
  permission. Never print the key.

Scripts live in `scripts/`. Each network gets a workspace directory (`<net>`) holding `config.json`, `raw/`,
`topology.json` and `out/`. Example config: `examples/example-net/config.json`.

## Stage 1: free APIs

**1a. Which ASNs make up the company?** Many operators run two or three ASNs: a main one, acquired
networks not yet merged, a cloud or data-centre arm. Map them together, so the links between them show.

```
python scripts/family.py <net> AS<seed> --names "former brand,acquired company,..."
```
It proposes siblings with evidence: same registry organisation (RDAP), same PeeringDB organisation, past
origins of the seed's prefixes, and name matches among BGP neighbours. Large networks that once originated
the seed's space are flagged `provider-of-space`: they assigned it out (e.g. Cogent `38.x` blocks) and are
not siblings. **Confirm siblings with the user before adding them**, because it changes the customer list
and the map. Then pass every family ASN to bootstrap and list them in `config.json` `"asns"`. Each router is
tagged with the ASN originating most of its addresses. Links between two family ASNs are drawn in orange
and labelled `ASx - ASy`.

**1b. Bootstrap.**

```
python scripts/bootstrap.py <net> AS<n> [AS<n> ...]
```
Writes `prefixes.txt`, `probe24.txt`, `neighbours.json`, `customer_inventory.json`, `customer_targets.txt`,
`ix_ports.json` and `facilities.json`. It also writes a skeleton `config.json` if none exists.

Then by hand, in a browser: open `bgp.he.net/AS<n>#_ix`. It lists IX ports PeeringDB may not (it found 4
extra in one test). Add them to `raw/ix_ports.json` with `"source": "bgp.he.net"`.

Read the upstreams in `neighbours.json`: a few high-"power" left neighbours are the real transit, and the
long tail is route-server peers. Customers listing more than 100 prefixes are dropped as leaks or artefacts.

## Stage 2: local discovery (the core; free and unlimited)

```
sudo sh scripts/local_discovery.sh <net> [pps]      # WSL: wsl -u root -e sh .../local_discovery.sh /mnt/c/.../<net>
python scripts/ingest_local.py <net>
```
The phases:
- **Preflight.** Checks the connection passes traceroute hops and UDP replies. It stops if not.
- **A.** One trace per /24.
- **B.** A sweep of the /24s that held router hops, plus the configured loopback blocks.
- **C.** A trace to every live address.
- **D.** Mercator and radargun alias resolution.
- **E.** One prefixscan per far address.
- **F.** Traces to customer targets.

It makes no DNS or web lookups, so it can run from any connection, including a laptop on public Wi-Fi. Run
the preflight first there: many hotspots drop ICMP or UDP and the run would be empty.

**Finding the loopback block.** Most operators number router IDs from one small block. Look for a /24 or /25
in which many addresses answer ping, never appear as a traceroute hop, and sit one hop past a router. Transit
LG BGP output also shows the operator's router IDs (stage 5). Put the block in `config.json` `"loopbacks"`
and rerun B-D. Every router group then gets exactly one loopback. **A group with two loopbacks means two
routers were wrongly merged.** That is the main check on alias resolution. Without a loopback block, every
group of 2+ interfaces is treated as a router.

## Stage 3: build and render

```
python scripts/build_topology.py <net>
python scripts/render.py <net>            # out/map.* and out/map_full.*  (SVG, PDF, PNG; deterministic)
python scripts/render_visio.py <net>      # out/map*.vsdx (native Visio: Visio draws at Graphviz's coordinates)
```
Do not use Graphviz's `-Tvdx`: Visio rejects it ("Unexpected end of file") even though the XML is valid.
Fill in `config.json` as evidence arrives:
- `pins`: addresses whose city is known from an LG or IX membership. These win over latency.
- `placement` rules.
- `pops` and `region_order`: the map's grouping.
- `transit.ic`: the operator-side handoff address mapped to the provider's router name.
- `ix_metro`.

## Stage 4a: reverse DNS and Globalping (free)

```
python scripts/rdns.py <net>
python scripts/place_globalping.py <net> "Chicago,Dallas,Denver,San Jose,Miami,St. Louis,Kansas City,..."
```
PTR records are mostly absent on operator routers. The transit provider's side of each handoff is usually
named, which gives the provider's router and an interconnect ID.

Globalping places routers by city. Use 2+ probes per city: one probe may sit on an ISP that routes the long
way (a Denver probe read 14.9 ms to a router Atlas measured at 1.1 ms). The script saves progress and
resumes within the hourly budget. Map city names to PoP codes in `placement.metro_to_pop`.

## Stage 4b: RIPE Atlas (credits)

```
python scripts/place_atlas.py <net> ping probes.json --inflight 5     # probes.json = {metro: [probe ids]}
```
Throttle. 531 one-offs aimed at the same 10 probes mostly failed: probes run only a few of your
measurements at once. **Before debugging your own setup**, check the platform: list recent public one-offs
(`/api/v2/measurements/?is_oneoff=true&start_time__gte=<now-3600>`). In Nov 2026, 97 of 100 failed
platform-wide while the status page showed nothing.

The most valuable Atlas use is **probes inside other networks**:
- **Inside the operator's customers** (`/api/v2/probes/?asn_v4=<customer asn>`). Their traffic leaves
  through the operator, so they see its attachment points from inside.
- **Inside its IX peers.** These see paths that only peers get.

## Stage 5: looking glasses (rate-limited; some need the user)

See `reference/looking_glasses.md`. In short:
- **HE (`lg.he.net`).** About 10 queries before a temporary block. Pick only HE routers in metros with
  evidence of the operator, not all 125. The `6939:7xxx` communities mark where HE learned a route; map
  them to cities by the lowest internal metric.
- **The transit provider's LG** (Arelion `lg.twelve99.net`). The user must solve a CAPTCHA, and after that
  each query needs a click on Run. `show bgp` gives:
  - which provider routers hold a session with the operator (external, best),
  - the operator's **router IDs** (from the neighbour line),
  - the operator's **communities** on each customer route. In one test, three community values grouped
    customers by the absorbed network or region.
- Traceroute from the provider's router into the operator shows the first operator router at that site.

## Stage 6: history becomes hypotheses

```
python scripts/history.py <net>
```
It writes three things:
- the upstream and customer-count timeline,
- earlier origin ASNs of today's prefixes (absorbed networks; look up the ASN's current holder with care,
  since ASNs get reassigned),
- router hops from **other people's** public Atlas traceroutes, with dates.

It prints old adjacencies missing from today's map. For archived network maps and PoP lists, hand
Wayback / web search to a cheap research subagent; the brief is in `reference/history.md`.

**Turn each finding into a test with stage 2 tools:**
- Does the old /31 still answer?
- Which routers own its two ends (radargun with the loopbacks)?
- Does a trace to the far end cross it directly, while traffic to that router's other addresses goes
  elsewhere? That means it is a standby link.

Record the results in `raw/extra_evidence.json` (links, devices, retired interfaces), then rebuild.

## Customers

```
python scripts/customer_attach.py <net>  &&  python scripts/build_customers.py <net>  &&  python scripts/build_topology.py <net>
```
**A customer's end of an operator-numbered /30 looks like an operator router.** Only alias-resolved
interfaces count as operator routers. For customers that never cross the operator from the local machine
(they are multihomed), check BGP paths in RIPEstat looking-glass data:
- if the transit provider's path goes through the operator, use that provider's LG (stage 5),
- if only IX peers' paths do, use Atlas probes inside those peers (stage 4b),
- best of all, trace from Atlas probes **inside the operator's own customers**. Their traffic leaves
  through the operator, and the operator prefers its customer routes, so the trace crosses the operator
  to every other customer. In the first run this placed the last six customers in one batch. Globalping
  had no probes in that small operator's cone.

**How each customer connects:**

```
python scripts/handoffs.py <net> plan && sudo sh scripts/handoff_probe.sh <net> && python scripts/handoffs.py <net> report
```
For every customer it reports:
- the attachment router,
- the handoff /31 or /30 and which side is whose (IP-ID confirmed where possible),
- the extra latency past the operator's router: a hint of radio or long haul versus same building,
- PTR names,
- the share of the customer's address space that RIS collectors see arriving through the operator.

Low shares mean a multihomed customer that sends most of its space through other upstreams.
**Negative "extra ms"** means the operator's router answers ICMP more slowly than the customer's edge.
That is control-plane noise, not distance.

## What it cannot see

- Links no measured path crosses.
- MPLS-hidden hops. An adjacency in a traceroute is not always a physical link.
- Port speeds, except IX ports as the operator lists them in PeeringDB.
- Jumbo MTU: path MTU discovery from a host is capped at its own 1500 bytes.
- Building-level location. Probes give a metro at best.
- **Location behind a single entry point.** If the operator reaches a region only through one hub, every
  probe's traffic passes the hub first. Latency then measures distance behind the hub, not geography. A
  suburban PoP looked identical to downtown, and Texas routers all read "Dallas + 5-18 ms" from 155
  Texas-area probes. Report the tiers behind the hub, and use names, customers and user knowledge for the
  town.
- IPv6-only customers when the operator's IPv6 hops don't answer. A looking glass can show the route
  entering the operator, but not where it attaches.

Say so in the report.

## Reporting

Lead with the answer to the user's question. For each claim, give the evidence type: alias-resolved,
prefixscan link, LG, latency, history or inference. Use dashed lines on the map for anything not proven.

See `reference/lessons.md` for the mistakes this method was built from.
