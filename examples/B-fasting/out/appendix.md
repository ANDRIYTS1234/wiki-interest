# Порівняй зростання інтересу до інтервального голодування в польськомовній та чеськомовній Wikipedia за останні два роки.

## Склад кошиків

### Інтервальне голодування (`target`, role: target)
- **cs**:
  - cs:Přerušovaný půst
- **pl**:
  - Q1666254, **missing**: no article in pl.wikipedia
  - pl:Głodówka lecznicza, proxy_for=Q1666254

## Методика

- **Дані:** Wikimedia Pageviews API, перегляди людей (`user`), щодня, з 2016-01; агрегати розділу для
  нормалізації. Перегляди редиректів і колишніх назв додано до основної назви (для часток ботів/пристроїв —
  лише основна стаття).
- **Вікно:** останні 24 повних місяців проти тих самих календарних місяців роком раніше (прибирає
  сезонність); бази з `baselines` порівнюють ті самі місяці в кожному вказаному році.
- **Панель:** статті, створені до початку базового періоду, з повними даними й не менш ніж
  `min_monthly_views`=30 переглядів на місяць у середньому за базовий період.
- **index_norm:** середнє геометричне по статтях панелі відношення (поточне+1)/(попереднє+1), поділене на
  таке саме відношення трафіку розділу. 95% bootstrap-інтервал по статтях (2000 перевибірок, seed
  0; не рахується при менш ніж 3 статтях у панелі).
- **share_change:** зміна сумарної частки панелі в трафіку розділу (на 1,000,000 переглядів).
- **Варіанти стійкості:** діапазон leave-one-out, без 3 найбільших статей, медіана відношень по статтях, без
  разових сплесків, без аномальних місяців (кожен — у таблиці нижче, якщо застосовний).
- **Сплески:** день понад spike_k=5.0× ковзної 29-денної медіани і не менш ніж
  spike_min_abs=30 переглядів понад неї; клас — за частками automated/desktop основної статті.
- **Аномальні місяці:** місяць, чиї перегляди перевищують anomaly_k=2.0× його типову частку календарного
  місяця (медіана за іншими повними роками), помножену на медіанний рівень того року; рахуються лише роки, коли
  вже існували всі статті панелі.
- **Правила довіри:**
  - *direction*:
    - Variants: the main estimate, leave-one-out minimum and maximum, without the top 3 articles, median of article ratios, without one-off spikes, without anomalous months (those that exist).
    - high: every variant has the same sign as the main estimate and the 95% interval of index_norm excludes 1 (no interval with fewer than 3 panel articles, so at most medium).
    - medium: every variant has the same sign, but the interval includes 1.
    - low: otherwise.
    - Caps: LOW_VOLUME, PANEL_SMALL or REDIRECTS_SKIPPED limit direction to medium.
  - *magnitude*:
    - spread = max / min of index_norm over the same variants.
    - high: spread <= magnitude_high and no SPIKE_DRIVEN or ANOMALY_MONTHS for this claim.
    - medium: spread <= magnitude_medium (or high blocked by those flags).
    - low: otherwise.
    - Caps: BOT_RECLASSIFICATION_2025 or PRE_2020_BOT_CLASS for the periods of this claim limit magnitude to medium.
  - *comparisons*:
    - direction high: the 95% interval of the ratio excludes 1; medium: the ratio differs from 1 by more than `flat` but the interval includes 1; low: otherwise. Fewer than min_panel common articles caps it at medium.
    - magnitude high: interval upper/lower <= 1.3; medium: <= 1.8; low: otherwise.

## Відомі обмеження

- **Літні хибні аномалії.** Детектор аномальних місяців (опис нижче) може позначити літній місяць на межі
  порогу в роки різкого спаду рік до року, бо рівень усього року (яким масштабується очікувана частка) сам
  занижений. До прапорця ANOMALY_MONTHS на межі порогу влітку варто ставитися обережніше, ніж до явного стрибка.
- **Швидкий режим журналу перейменувань.** За замовчуванням `resolve` перевіряє журнал переміщень лише для
  поточних редиректів сторінки, не для назви без уточнення в дужках (`--moves full` перевіряє обидва варіанти).
  Колишню назву, яку тепер зайняла інша стаття (наприклад uk «Марс» → «Марс (планета)»), у цьому режимі можна
  не знайти: перегляди до перейменування тоді не додаються. Це не стосується колишньої назви, яка й зараз є
  редиректом (звичайний випадок) — її знаходять і підсумовують завжди.

## Прапорці якості

| code | severity | scope | detail |
|---|---|---|---|
| NEW_ARTICLE | info | target.cs | created after history_start: Přerušovaný půst |
| PANEL_SMALL | warning | target.cs.baseline:2022 | no estimate (empty_panel); panel has 0 articles |
| ANOMALY_MONTHS | warning | target.cs.window | anomalous months inside the compared periods: 2025-04, 2025-04, 2025-09, 2025-12 |
| BOT_RECLASSIFICATION_2025 | info | target.cs.window | compared periods include March-August 2025, when Wikimedia reclassified bot traffic |
| BOT_SUSPECT | warning | target.cs.window | automated jumps or bot-like spikes in: 2025-05, 2025-05, 2026-06 |
| PANEL_SMALL | warning | target.cs.window | 1 articles in the panel (min_panel 5) |
| ARTICLE_MISSING | warning | target.pl | no article in pl.wikipedia for: Q1666254 |
| PROXY_USED | warning | target.pl | non-equivalent substitutes: pl:Głodówka lecznicza (for Q1666254) |
| BOT_RECLASSIFICATION_2025 | info | target.pl.baseline:2022 | compared periods include March-August 2025, when Wikimedia reclassified bot traffic |
| BOT_SUSPECT | warning | target.pl.baseline:2022 | automated jumps or bot-like spikes in: 2025-07, 2025-09, 2026-06, 2026-07 |
| PANEL_SMALL | warning | target.pl.baseline:2022 | 1 articles in the panel (min_panel 5) |
| BOT_RECLASSIFICATION_2025 | info | target.pl.window | compared periods include March-August 2025, when Wikimedia reclassified bot traffic |
| BOT_SUSPECT | warning | target.pl.window | automated jumps or bot-like spikes in: 2025-07, 2025-07, 2025-09, 2026-06, 2026-07 |
| LOW_VOLUME | warning | target.pl.window | median monthly views of the panel in the base period are below low_volume_month |
| PANEL_SMALL | warning | target.pl.window | 1 articles in the panel (min_panel 5) |

## Стійкість (change_norm за варіантом)

| basket | lang | window | loo_min | loo_max | no_top3 | median | no_spikes | no_anomalies |
|---|---|---|---|---|---|---|---|---|
| target | cs | −31% | — | — | — | −31% | −35% | −34% |
| target | pl | −15% | — | — | — | −15% | −15% | — |

## Джерела

- Wikimedia Pageviews REST API (`wikimedia.org`), MediaWiki Action API, Wikidata API.
- wiki-interest 0.1.0

## Як відтворити

```bash
wiki-interest fetch --spec analysis.json
wiki-interest analyze --spec analysis.json
wiki-interest report --metrics metrics.json --narrative narrative.json --out report.pdf
```

- `tool_version`: 0.1.0
- `data_as_of`: 2026-08
- languages: pl, cs; window: 24 months ending 2026-08
- history from 2016-01; baselines: 2022
- date range fetched: 2016-01-01..2026-08-31
