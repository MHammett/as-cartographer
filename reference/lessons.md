# Lessons from the first full run (Nov 2026)

These come from mapping a regional ISP of about 35 routers across a dozen metros. Each one cost real time.

1. **Latency alone misleads.** An IX port whose next hop was 21 ms away was read as "everything is hauled
   to the hub". Traceroute, alias resolution and the transit provider's LG later showed five routers in
   that metro and a direct link to the next city. Use latency to place routers, not to infer structure.
2. **Tracing to a router's own address doesn't reveal the router.** It replies from the address you
   probed, so Mercator found 1 alias in 1,503 probes. IP-ID (radargun) plus /31-/30 mates (prefixscan)
   did the work.
3. **The loopback block is the anchor.** One address per router in a single /25 turned interface groups
   into a router census, and "no group holds two loopbacks" became the check on alias resolution.
4. **Customer edges look like operator routers.** An address first called "the St. Louis router" was a
   customer's end of an operator-numbered /30.
5. **Don't flood Atlas.** 531 one-offs to 10 probes mostly failed. Throttle, and spread across probes.
   Check whether Atlas is failing for everyone before debugging your own setup.
6. **HE's LG blocks after about 10 quick queries.** Narrow to metros with evidence first.
7. **Don't over-claim from one data source.** "No router in Miami" was wrong. No trace had crossed it;
   alias resolution plus a ping from a probe in that city found it.
8. **Link RTT.** min over probes of rtt(A)+rtt(B) works. |rtt(A)-rtt(B)| as a lower bound does not:
   routing asymmetry breaks it.
9. **Graphviz `-Tvdx` doesn't open in Visio.** Draw the `.vsdx` through Visio's object model at
   Graphviz's coordinates (`render_visio.py`).
10. **History is for hypotheses, not decoration.** Old public traces showed a link between two regions
    that no current trace crossed. Testing it showed the /31 still alive but not preferred: a standby
    link.
11. **Prefixscan on every hop pair is slow.** 574 pairs ran for 40+ minutes. One test per far address is
    enough.
12. **ASNs get reassigned.** ASNs that originated the target's space in 2015 now belong to unrelated
    organisations, so look up the holder as of the date in question.
13. **The local vantage point was itself inside the target's customer cone**, through a downstream ISP.
    Check yours first. It changes what traces show, and it makes the probes attributable to someone the
    target knows.
14. **A hub hides geography.** When an operator reaches a region only through one hub, every external
    probe's path passes the hub first. A suburban PoP read the same as downtown, and 25 routers in one region
    read "hub + 5-18 ms" from 155 probes across that region. Report tiers behind the hub. Get towns from router
    names (a three-letter town code in one gateway PTR named its site), from the customers each router serves, and from the
    user.
15. **Probes inside the operator's customers are the best vantage point.** They placed six multihomed
    customers that no outside trace crossed. Check `asn_v4` for Atlas probes in each customer ASN early.
16. **Some transit-LG targets interrupt the query.** Arelion's traceroute stops with "Query interrupted"
    when later hops don't answer, as the operator's IPv6 hops didn't. The first hop still names the
    interconnect.
