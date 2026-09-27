# Limits of Wikimedia pageview data

- Pageviews measure attention to reference content, not intent to learn or pay.
- Readers increasingly get answers from search snippets and AI assistants; whole editions lost 10–40% of human views in 2023–2026. Normalized metrics correct for the edition-wide decline, not for topic-specific shifts in where people look.
- Bots: the `automated` class exists only from May 2020; earlier "human" views include some bots. In 2025 Wikimedia reclassified traffic from bots that evaded detection (March–August 2025), so comparisons across that period can overstate declines.
- Language ≠ country: Spanish Wikipedia readers are spread across many countries; the API gives no geography.
- Missing articles: small editions lack many topics; absence is not evidence of low demand.
- Rate limits: the User-Agent carries `WIKI_INTEREST_CONTACT` or, if unset, the project URL — measured to be as fast as an email (~0.8 s/request). A User-Agent with no contact at all was ~4× slower with frequent HTTP 429; the CLI never sends one.
- Large baskets (hundreds of titles with redirects) take tens of minutes to download the first time; later runs use the local cache.
