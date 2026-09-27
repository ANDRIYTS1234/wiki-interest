# Limits of Wikimedia pageview data

- Pageviews measure attention to reference content, not intent to learn or pay.
- Readers increasingly get answers from search snippets and AI assistants; whole editions lost 10–40% of human views in 2023–2026. Normalized metrics correct for the edition-wide decline, not for topic-specific shifts in where people look.
- Bots: the `automated` class exists only from May 2020; earlier "human" views include some bots. In 2025 Wikimedia reclassified traffic from bots that evaded detection (March–August 2025), so comparisons across that period can overstate declines.
- Language ≠ country: Spanish Wikipedia readers are spread across many countries; the API gives no geography.
- Missing articles: small editions lack many topics; absence is not evidence of low demand.
- Rate limits: without a contact in the User-Agent (`WIKI_INTEREST_CONTACT`, defaults to the project URL) downloads are ~4× slower and hit HTTP 429.
- Large baskets (hundreds of titles with redirects) take tens of minutes to download the first time; later runs use the local cache.
