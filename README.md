# as-cartographer

Router-level maps of any network, built from the outside: which routers it has, where they are, how they
link, where its upstreams, IX ports and customers attach, and how its sibling ASNs interconnect.

The output is a deterministic map: Graphviz SVG/PDF/PNG plus a native Visio `.vsdx`, regenerated from a
single `topology.json`. Every router, link and location in that file carries the evidence behind it.

It is written as a [Claude Code](https://claude.com/claude-code) skill (`SKILL.md`), and the scripts run
on their own too.

## How it works, cheapest first

| Stage | Source | Cost |
|---|---|---|
| 1 | RDAP, RIPEstat and PeeringDB: sibling ASNs, prefixes, neighbours, customers, IX ports | free |
| 2 | Local probing with [scamper](https://www.caida.org/catalog/software/scamper/): traceroute, IP-ID alias resolution (radargun), /31-/30 link mates (prefixscan) | free, local |
| 3 | Offline build and render | free |
| 4 | Reverse DNS; [Globalping](https://globalping.io) and [RIPE Atlas](https://atlas.ripe.net) probes to place routers by city | free, or credits |
| 5 | Public looking glasses: BGP sessions, router IDs, communities | rate-limited; some need a person |
| 6 | History (RIPEstat routing history, public Atlas traces, archived web pages), turned into hypotheses and retested with stage 2 | free |

`SKILL.md` has the full method, and `reference/` covers looking-glass mechanics, the history brief and the
lessons learned.

## Requirements

- Python 3.10+ (standard library only for the core).
- Linux, or WSL on Windows: `sudo apt install scamper fping graphviz python3`.
- Optional:
  - Microsoft Visio and `pywin32`, for `.vsdx` output.
  - A RIPE Atlas API key, for stage 4b.
  - A Globalping token, for a higher hourly limit.

## Use it as a Claude Code skill

```
git clone https://github.com/MHammett/as-cartographer.git ~/.claude/skills/as-cartographer
```
On Windows, use `%USERPROFILE%\.claude\skills\as-cartographer`. Claude Code picks the skill up in new
sessions; ask it to "map AS<n>". Keep each network's workspace outside the skill folder, for example
`~/as-cartographer-work/AS<n>`.

## Quick start

```
python scripts/family.py work/AS64500 AS64500 --names "former brand"   # pick sibling ASNs with the user
sudo sh scripts/run_all.sh work/AS64500 AS64500 AS64501                # every no-judgment stage, ~45-75 min
```

Then add evidence: placement pings, reverse DNS, pins from looking glasses, customers and history (see
`SKILL.md`), and rebuild. Keep each network's workspace (`work/…`) outside this repository.

## Responsible use

- **Probe gently.** The defaults are about 100 packets per second of ICMP and UDP from one host. Each
  address gets a handful of probes, and nothing scans ports or carries a payload. Don't raise the rate
  against networks you don't operate.
- **Respect public services.** Looking glasses, Globalping and RIPE Atlas are shared resources with terms
  of use and rate limits. The scripts throttle and stop at the limits. Never automate around a CAPTCHA;
  a person solves it.
- **Measurement only.** This maps what a network shows to anyone who sends it traffic. It does not log
  in to anything, guess credentials, or exploit anything, and it must not be extended to.
- **Test it on your own network first.** You know the ground truth there, so you can see what the method
  gets right and wrong before relying on it elsewhere.

## Prior art

This orchestrates well-known techniques rather than inventing new ones:
- CAIDA's [scamper](https://www.caida.org/catalog/software/scamper/) does the probing and the alias
  resolution.
- CAIDA's [Internet Topology Data Kit](https://www.caida.org/catalog/datasets/internet-topology-data-kit/)
  builds Internet-wide router graphs with MIDAR, iffinder and bdrmapIT. Snapshots older than a year are
  public and can supplement stage 6.
- Rocketfuel (Spring, Mahajan and Wetherall, SIGCOMM 2002) first mapped individual ISPs at router level
  from outside.

What this adds is the practical part: cheapest-source-first ordering, sibling-ASN families, customer
attachment, looking-glass and BGP-community evidence, history as testable hypotheses, and a reproducible
map.

## Tests

```
python tests/test_offline.py
```
It builds and renders a made-up 3-router, 2-ASN network (documentation addresses) without probing anything.

## License

MIT. See `LICENSE`.
