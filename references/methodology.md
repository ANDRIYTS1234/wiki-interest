# Methodology (short)

- **Data:** Wikimedia Pageviews API, human (`user`) views, daily, from `history_start` (API data begins July 2015); totals of each language edition for normalization. Views of all redirects and former titles (user/all-access only) are added to each article; a former title counts only until its move date. `automated` does not exist before May 2020 and is marked unavailable, not zero.
- **Window:** last N complete months vs the same calendar months one year earlier (removes seasonality). Extra baselines compare the same months of chosen years.
- **Normalization:** views per million views of the whole language edition.
- **Basket index (`index_norm`):** geometric mean over panel articles of (current / previous), divided by the same ratio of edition traffic. Every article weighs equally. 95% bootstrap interval over articles (2000 resamples, fixed seed).
- **Share change (`share_change`):** change of the basket's summed share of edition traffic; big articles weigh more.
- **Robustness:** leave-one-out range, without top-3 articles, median of article ratios, without one-off spike days, without anomalous months, alternative baselines.
- **Spikes:** a day above k× (default 5) the rolling 29-day median and above a minimum absolute increase; bot and desktop shares are checked on the main article.
- **Anomalous months:** a month above `anomaly_k` (2×) its typical share of the year times that year's level; automated jumps are flagged separately (`BOT_SUSPECT`).
- **Panel:** articles created before the base period, present in every compared language, with at least `min_monthly_views` in the base period; the rest are listed with a reason (`created_after:<date>`, `partial_data`, `low_volume`; items with `exclude` or missing in a language are listed in the basket composition).
- **Language comparison (`compare`):** ratio of basket indices over common QIDs with a bootstrap interval; target vs control uses the ratio of indices, never of sums.
- **History:** yearly normalized values, peak year, current as % of peak; article creation dates are flagged.
- **Confidence rules:** direction high if all robustness variants agree in sign and the interval excludes no change; medium if the sign agrees but the interval includes no change; low otherwise. Magnitude high if variants stay within 1.15×, medium within 1.35×. Fewer than 3 panel articles → no interval. Some flags cap confidence (see interpreting.md).
- All parameters and their defaults are written to `metrics.json` and the appendix.
