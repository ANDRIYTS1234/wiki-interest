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
- Always give the reasons in one short clause: `<basket>.<lang>.confidence.window.reasons[]` (or `.baselines.<year>`) in metrics.json.
- Caps: `LOW_VOLUME`, `PANEL_SMALL`, `REDIRECTS_SKIPPED` → direction at most medium; `BOT_RECLASSIFICATION_2025`, `PRE_2020_BOT_CLASS` → magnitude at most medium for that comparison. With fewer than 3 panel articles there is no interval, so direction is at most medium.

## Flags → what the reader sees and what you add

`report` prints every flag in the PDF's caveats block automatically, in the reader's language, plus one line for
every comparison `analyze` marked `DO NOT COMPARE DIRECTLY`. You do not need to repeat them in `caveats`; use
`caveats` only for what the flags do not cover. In the chat answer, mention the flags that change the conclusion.

| Flag | Printed in the PDF | What you add |
|---|---|---|
| LOW_VOLUME | Few views per month; small changes look large. Treat as a weak signal. | Call the result a weak signal. |
| SPIKE_DRIVEN | The change depends on one-off spikes (news, a viral post); the appendix shows the result without them. | Give the number without spikes too (`variants.no_spikes`). |
| ANOMALY_MONTHS | Some months are abnormal (often unfiltered bots); the appendix shows the result without them. | Give the result without them (`variants.no_anomalies`). |
| BASKET_SENSITIVE | The result depends on which articles are included; treat the magnitude as uncertain. | Do not state the magnitude as firm. |
| CONCENTRATION_DIVERGENCE | A few big articles move differently from the rest of the topic. | Name the articles (the flag's detail lists them). |
| BOT_SUSPECT | Part of the traffic looks automated. | Mention it when the change is large. |
| ARTICLE_MISSING | No article in that language: a gap in Wikipedia, not proof of no demand. | Say it is a gap in Wikipedia, not missing demand. |
| PROXY_USED | A related but different article stands in; it is not compared directly with other languages. | Never compare the stand-in directly with another language. |
| NEW_ARTICLE | An article was created during the period; early growth may just be the article being new. | Do not call early growth a trend. |
| PRE_2020_BOT_CLASS | Before May 2020 Wikimedia did not separate bots; the old baseline may be inflated. | Prefer a baseline from 2021 or later for the headline. |
| BOT_RECLASSIFICATION_2025 | Wikimedia reclassified bot traffic in Mar–Aug 2025; year-over-year changes across that period may be overstated. | Say year-over-year declines across 2025 may be overstated. |
| PANEL_SMALL | Few comparable articles in the panel; a weak basis for a conclusion. | Suggest adding comparable articles to the basket. |
| REDIRECTS_SKIPPED | Quick pass without redirects; the result is preliminary. | Rerun fetch without `--redirects none` before a final answer. |
| PARTIAL_DATA | Some series failed to download; the result rests on incomplete data. | Name what is missing. |
| UNUSED_SERIES | Some downloaded series are not used in any basket. | Explain it or remove it from the spec. |

## narrative.json

```json
{
  "title": "Is interest in astronomy growing in Ukrainian Wikipedia?",
  "answer": "No. The topic's share of attention changed by {target.uk.window.change_norm:pct} over the last year.",
  "findings": ["...", "..."],
  "recommendation": "...",
  "next_steps": ["Check search volume for ...", "Run a landing-page test ..."],
  "caveats": ["..."]
}
```

- Numbers only via placeholders copied from `placeholders` in the analyze output. Formats: `pct` for `change_norm`/`share_change` (fractions → signed %), `x` for `index_norm` and `compare…ratio`, `ci` for `…_ci` intervals, `int` for counts. `{path:pct}` on `index_norm` is wrong (0.85 would print as +85%). Four-digit years (2019) may be written directly; any other digit is rejected.
- Paths: `<basket>.<lang>.window.<metric>`, `<basket>.<lang>.baselines.<year>.<metric>`, `<basket>.<lang>.groups.<group>.window.<metric>`, `compare.<basket>.<l1>_vs_<l2>.window.ratio`, `compare.<target>_vs_<control>.<lang>.window.ratio`.
- Up to 4 findings. Mark causes as "[hypothesis]" unless sourced.
- Answer first, then why, then what to do. No methodology in the main text — it goes to the appendix automatically.
- Write in the user's language; set `--report-lang` accordingly (uk or en).
