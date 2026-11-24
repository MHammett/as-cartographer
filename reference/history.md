# History stage: brief for a research subagent

Use a cheap model in the background. Give it this brief with the names filled in:

> Find historical network maps and network descriptions for <operator>, AS<n>, which has also traded as
> <former names / domains / acquired companies>. Use the Wayback Machine, including the CDX API:
> `https://web.archive.org/cdx/search/cdx?url=DOMAIN/*&output=json&filter=mimetype:image/*&collapse=urlkey`
> for images, and the same query without the filter for pages, plus web search and press releases.
>
> Report:
> 1. every archived network map image or network/PoP page, with Wayback URL and date, describing what an
>    image shows (cities, links, capacities, buildings);
> 2. dated PoP lists and backbone descriptions;
> 3. acquisitions and rebrands, with dates;
> 4. anything about <specific claim the user remembers>.
>
> Separate what you saw from what you infer. Keep it under 900 words. Don't log in or submit forms.

What useful output looked like in the first run:
- **Dated PoP lists from three different years.** A suburban PoP first appeared in the middle list. That
  matched the user's memory of an old map, and it pointed at two candidate routers to test.
- **A backbone map image** referenced on an archived page but never archived itself.
- **Two acquisitions with dates.** The later one matched a change in routing seen in traceroutes, which
  explained a backhaul that looked wasteful.

Turn each PoP that the old lists name but today's map lacks into a test: ping the router loopbacks from
probes in that city (Globalping or Atlas). A loopback answering in about 1 ms from there means a router
there.
