# Чи зростає інтерес до астрономії в uk.wikipedia?

## Склад кошиків

### Інші природничі науки (`control`, role: control)
- **uk**:
  - uk:Геологія
  - uk:Географія
  - uk:Хімія
  - uk:Математика
  - uk:Фізика
  - uk:Біологія
  - uk:Зоологія
  - uk:Ботаніка
  - uk:Екологія
  - uk:Генетика

### Астрономія (`target`, role: target)
- **uk**:
  - uk:Всесвіт
  - uk:Марс (планета)
  - uk:Сатурн (планета)
  - uk:Меркурій (планета)
  - uk:Венера (планета)
  - uk:Галактика
  - uk:Юпітер (планета)
  - uk:Чумацький Шлях
  - uk:Великий вибух
  - uk:Комета
  - uk:Астероїд
  - uk:Місяць (супутник)
  - uk:Нейтронна зоря
  - uk:Телескоп
  - uk:Екзопланета
  - uk:Зоря
  - uk:Сонце
  - uk:Сонячна система
  - uk:Чорна діра
  - uk:Сузір'я

## Методика

- **Дані:** Wikimedia Pageviews API, перегляди людей (`user`), щодня, з 2016-01; агрегати розділу для
  нормалізації. Перегляди редиректів і колишніх назв додано до основної назви (для часток ботів/пристроїв —
  лише основна стаття).
- **Вікно:** останні 12 міс. проти попередніх 12 (повні місяці; база зсунута на 1 ціл. р., тож не перекривається з вікном
  і порівнює ті самі календарні місяці — сезонність прибрано); бази з `baselines` порівнюють ті самі місяці
  в кожному вказаному році.
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
| ANOMALY_MONTHS | warning | control.uk.baseline:2019 | anomalous months inside the compared periods: 2026-08 |
| BOT_SUSPECT | warning | control.uk.baseline:2019 | automated jumps or bot-like spikes in: 2025-12, 2026-01, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| PRE_2020_BOT_CLASS | info | control.uk.baseline:2019 | the base period is before May 2020, when bots were still counted as users |
| ANOMALY_MONTHS | warning | control.uk.baseline:2021 | anomalous months inside the compared periods: 2026-08 |
| BOT_SUSPECT | warning | control.uk.baseline:2021 | automated jumps or bot-like spikes in: 2025-12, 2026-01, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| ANOMALY_MONTHS | warning | control.uk.window | anomalous months inside the compared periods: 2026-08 |
| BOT_RECLASSIFICATION_2025 | info | control.uk.window | compared periods include March-August 2025, when Wikimedia reclassified bot traffic |
| BOT_SUSPECT | warning | control.uk.window | automated jumps or bot-like spikes in: 2025-05, 2025-12, 2026-01, 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| BOT_SUSPECT | warning | target.uk.baseline:2019 | automated jumps or bot-like spikes in: 2025-09, 2026-01, 2026-04, 2026-06, 2026-07, 2026-08 |
| PRE_2020_BOT_CLASS | info | target.uk.baseline:2019 | the base period is before May 2020, when bots were still counted as users |
| BOT_SUSPECT | warning | target.uk.baseline:2021 | automated jumps or bot-like spikes in: 2025-09, 2026-01, 2026-04, 2026-06, 2026-07, 2026-08 |
| ANOMALY_MONTHS | warning | target.uk.window | anomalous months inside the compared periods: 2025-01, 2025-02, 2025-08 |
| BOT_RECLASSIFICATION_2025 | info | target.uk.window | compared periods include March-August 2025, when Wikimedia reclassified bot traffic |
| BOT_SUSPECT | warning | target.uk.window | automated jumps or bot-like spikes in: 2025-09, 2026-01, 2026-04, 2026-06, 2026-07, 2026-08 |

## Стійкість (change_norm за варіантом)

| basket | lang | window | loo_min | loo_max | no_top3 | median | no_spikes | no_anomalies |
|---|---|---|---|---|---|---|---|---|
| control | uk | −49% | −51% | −48% | −49% | −51% | −49% | −50% |
| target | uk | −35% | −36% | −34% | −35% | −37% | −36% | −32% |

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
- languages: uk; window: 12 months ending 2026-08
- history from 2016-01; baselines: 2019, 2021
- date range fetched: 2016-01-01..2026-08-31
