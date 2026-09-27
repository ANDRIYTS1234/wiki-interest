# Methodology (short)

- **Data:** Wikimedia Pageviews API, human (`user`) views, daily, from July 2015; totals of each language edition for normalization. Views of all redirects and former titles are added to each article.
- **Window:** last N complete months vs the same calendar months one year earlier (removes seasonality). Extra baselines compare the same months of chosen years.
- **Normalization:** views per million views of the whole language edition.
- **Basket index (`index_norm`):** geometric mean over panel articles of (current / previous), divided by the same ratio of edition traffic. Every article weighs equally. 95% bootstrap interval over articles (2000 resamples, fixed seed).
- **Share change (`share_change`):** change of the basket's summed share of edition traffic; big articles weigh more.
- **Robustness:** leave-one-out range, without top-3 articles, median of article ratios, without one-off spike days, without anomalous months, alternative baselines.
- **Spikes:** a day above k× (default 5) the rolling 29-day median and above a minimum absolute increase; bot and desktop shares are checked on the main article.
- **Anomalous months:** a month's share of the year far above its usual seasonal share, or a jump in automated traffic.
- **History:** yearly normalized values, peak year, current as % of peak; article creation dates are flagged.
- **Confidence rules:** direction high if all robustness variants agree in sign and the interval excludes no change; medium if the sign agrees but the interval includes no change; low otherwise. Magnitude high if variants stay within 1.15×, medium within 1.35×. Some flags cap confidence (see interpreting.md).
- All parameters and their defaults are written to `metrics.json` and the appendix.
