# Interpreting results for founders

## The headline

- `index_norm` — typical change of an article in the basket relative to the whole language edition's traffic. >1 (or positive %) = the topic gains share of attention. Main number.
- `share_change` — change of the basket's total share of traffic. If it disagrees in sign with `index_norm` you get `CONCENTRATION_DIVERGENCE`: a few large articles behave differently from the rest; say which (the flag lists them).
- Raw views change is context only: whole Wikipedia editions lost 10–40% of traffic in 2023–2026, so raw declines exaggerate lost interest.

## Confidence

`direction_confidence` and `magnitude_confidence` are separate. Say both, in plain words:

- high direction: "the decline is consistent across all checks"
- medium direction: "the direction holds, but the uncertainty range includes no change"
- low direction: "the data does not support a clear direction"
- Always give the reasons from `confidence.reasons[]` in one short clause.

## Flags → what to tell the user

| Flag | Say |
|---|---|
| LOW_VOLUME | Few views per month; small changes look large. Treat as a weak signal. |
| SPIKE_DRIVEN | The change depends on one-off spikes (news, a viral post). Give the number without spikes too. |
| ANOMALY_MONTHS | Some months are abnormal (often unfiltered bots). Give the result without them. |
| BASKET_SENSITIVE | The result depends on which articles are included. Treat the magnitude as uncertain. |
| CONCENTRATION_DIVERGENCE | A few big articles move differently from the rest; name them. |
| BOT_SUSPECT | Part of the traffic looks automated. |
| ARTICLE_MISSING | No article in that language: a gap in Wikipedia, not proof of no demand. |
| PROXY_USED | A related but different article stands in; do not compare it directly with other languages. |
| NEW_ARTICLE | Article created during the period; early growth may just be the article being new. |
| PRE_2020_BOT_CLASS | Before May 2020 Wikimedia did not separate bots; the old baseline may be inflated. |
| BOT_RECLASSIFICATION_2025 | Wikimedia reclassified bot traffic in Mar–Aug 2025; year-over-year changes across that period may be overstated. |
| PANEL_SMALL | Fewer than 5 comparable articles; weak basis. |
| REDIRECTS_SKIPPED | Quick pass without redirects; rerun fully before a final answer. |
| PARTIAL_DATA | Some series failed to download; name what is missing. |
| UNUSED_SERIES | Something was downloaded but not used; explain or remove it. |

## narrative.json

```json
{
  "title": "Is interest in astronomy growing in Ukrainian Wikipedia?",
  "answer": "No. The topic's share of attention fell by {target.uk.window.index_norm:pct} over the last year.",
  "findings": ["...", "..."],
  "recommendation": "...",
  "next_steps": ["Check search volume for ...", "Run a landing-page test ..."],
  "caveats": ["..."]
}
```

- Numbers only via placeholders copied from the analyze output. Years (2019) may be written directly.
- Up to 4 findings. Mark causes as "[hypothesis]" unless sourced.
- Answer first, then why, then what to do. No methodology in the main text — it goes to the appendix automatically.
- Write in the user's language; set `--report-lang` accordingly (uk or en).
