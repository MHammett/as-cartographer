# Looking glasses: what works, and how

All of these run in a browser. Use the built-in browser or Chrome tools, and read results from the page
with JavaScript.

## Hurricane Electric (lg.he.net)

- **Form posts to `/`.** Fields: `token` (hidden, from the page), `routers[]` (e.g. `core3.chi1.he.net`),
  `command` (`bgproute`, `ping`, `traceroute`, `bgpsummary4`), `ip`, `raw=1`, `afPref=4`. Fetch it from
  the page context with FormData and read `#lg_return` from the response.
- **Rate limit.** About 10 queries, then "This client is temporarily blocked". Space queries 9+ seconds
  apart, choose routers in metros with evidence of the target, and retry after a few minutes. Querying all
  125 routers gets you blocked almost at once.
- **`show bgp <prefix>`.** Each path's `NEXT_HOP` is the HE border router that learned it, with an IGP
  metric. The community `6939:7xxx` marks where it was learned, and the router with the lowest metric for
  a given 7xxx is in that city. An `external` path means that HE router holds the session itself. In one
  test, six such codes mapped cleanly to six cities.
- The bgp.he.net AS page has a `#_ix` tab with IX ports PeeringDB may lack, and a `#_peers` tab, mostly
  route-server peers.

## The transit provider's LG (Arelion, lg.twelve99.net)

- **CAPTCHA.** reCAPTCHA needs a person: open the page and ask the user to solve it. URL parameters
  (`?type=bgp&router=chi-b23&address=1.2.3.4`) prefill the form. After the CAPTCHA, the first URL may
  auto-run; later ones need a click on **Run**, so navigate, click Run, wait about 8 s, then read the text
  after the last `BGP routing table entry` or `Command:`.
- **`show bgp`** on a router that holds the customer session shows the path as `external, best` with the
  neighbour IP. That is the operator-side address of the handoff. The `(x.x.x.x)` after it is the
  operator's **router ID**.
- **Other provider routers** show `internal` with `Originator: ... (<router name>)`, which names the
  provider router that holds the session.
- **Customer routes** carry the operator's own communities (e.g. `<operator asn>:320`) on the received-only copy.
  Collect them for many customers with known attachment and look for a pattern (region, absorbed
  network, PoP).
- **Traceroute** from the provider's router to an operator address: hop 1 is the operator's router at
  that site.
- **"Query interrupted"** on traceroutes to unresponsive targets. Use a target that answers, or use `bgp`.
- Arelion's side of each handoff has PTR `<router>-link.ip.twelve99.net`, and the operator side
  `<customer>-ic-<id>.ip.twelve99-cust.net`. An older interconnect ID or name hints at an older contract.

## RIPEstat looking-glass (no browser)

- `https://stat.ripe.net/data/looking-glass/data.json?resource=<prefix>` gives the AS paths seen by RIS
  collectors, in `rrcs[].peers[].as_path`.
- Use it to see which neighbours reach a customer through the target, i.e. paths ending
  `<target> <customer>`, before choosing which LG or Atlas probe to trace from.
