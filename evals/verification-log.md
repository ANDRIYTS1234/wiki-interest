# Журнал незалежних перевірок

Для кожного етапу: що заявив агент, що перевірено власноруч, розбіжності.

## Етап 0 — каркас (27.09.2026)

Заявлено агентом: 38 тестів, doctor healthy, коміт d8ac365, запушено.

Перевірено: git log, pytest, doctor, git status.
- pytest: 38 passed.
- doctor: healthy true, єдине попередження — не задано контакт User-Agent; Python 3.14.3 (uv обрав свою збірку замість системного 3.12).
- git status: чисто, але гілка випереджає origin/master на 1 коміт.

Розбіжності:
- Етап 0 не був запушений на GitHub, хоча агент мав це зробити.
- Python 3.14 замість 3.12; виправлено додаванням .python-version.

## Етап 1 — resolve (27.09.2026)

Заявлено агентом: 62 тести, коміти 0df8205 і dfb9353, регресійні кейси з розділу 6 SPEC пройдені; push чекав на явне підтвердження.

Перевірено: git log, pytest, власний кейс, якого немає у фікстурах агента (uk «шахи» як запит; pt «Regras do xadrez» за назвою; мови de, es, pt).
- pytest: 62 passed.
- pt «Regras do xadrez» → redirect_resolved, «Leis do xadrez» (Q3392263). Провал baseline D (редирект замість статті про правила) закрито й для мови, якої не було у фікстурах.
- es → «Leyes del ajedrez», колишні назви «Reglas del ajedrez» (2008-05-13) і «Reglamento del ajedrez» (2016-05-25).
- de → missing, пошукові збіги позначені як нееквівалентні; мовчазної заміни немає.
- uk «шахи» → needs_choice з 5 кандидатами (гра Q718 і три населені пункти з тією ж назвою); підказка в attention.
- Повторний прогін не перевірявся; агент заявив 0 запитів із кешу.

Розбіжності:
- Позначка Q3392263 виведена як «leis doxadrez» без пробілу; передано агенту на перевірку.
- Етап 0 на момент перевірки був запушений лише частково (origin/master на 0df8205, dfb9353 ще локально).

## Етап 2 — fetch (27.09.2026)

Заявлено агентом: 91 тест, коміт 8f007e5, дозавантаження лише відсутнього, --dry-run, прогрес у stderr.

```
96320e2 Baseline D: final protocol after coaching
8f007e5 Stage 2: fetch with incremental coverage, dry-run and progress
dfb9353 Stage 1: resolve with recorded fixtures and SPEC §6 regression tests
0df8205 doctor: exit 1 with ok=false when a check fails; pin Python 3.12 locally
91 passed in 13.70s
--- dry-run (очікую 0 запитів, оцінку кількості) ---
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","dry_run":true,"range":{"start":"2025-01-01","end":"2026-08-31"},"series":9,"series_cached":0,"requests_needed":9,"estimated_seconds":5,"estimated_minutes":0.1,"missing_articles":[],"unresolved":[]}
--- перший прогін ---
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","range":{"start":"2025-01-01","end":"2026-08-31"},"requests":9,"resolve_requests":0,"cache_hits":0,"series":9,"missing_series":[],"missing_series_count":0,"missing_articles":[],"result_file":"wiki-interest-out\\fetch_result.json"}

real	0m5.004s
user	0m0.000s
sys	0m0.015s
--- повторний прогін (очікую 0 запитів) ---
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","range":{"start":"2025-01-01","end":"2026-08-31"},"requests":0,"resolve_requests":0,"cache_hits":9,"series":9,"missing_series":[],"missing_series_count":0,"missing_articles":[],"result_file":"wiki-interest-out\\fetch_result.json"}
```

Висновок:
- pytest: 91 passed.
- Вхід — редирект pt «Regras do xadrez»; fetch сам узяв справжню статтю з кешу resolve (resolve_requests 0).
- 9 серій = 3 для основної статті + 4 редиректи (лише user) + 2 агрегати розділу; збігається з рішенням про редиректи.
- dry-run: оцінка 5 с, реальний прогін 5,0 с. Повторний прогін: 0 запитів, 9 з кешу.

Розбіжності:
- «leis doxadrez» з етапу 1 — хибна тривога: пробіл загубився при копіюванні з терміналу на місці переносу рядка. Агент перевірив Wikidata і вивід, додав тест на незмінність позначок.
- Етап 2 на момент перевірки не запушений; агент чекав підтвердження на push.
]633;E;{   echo\x3b   echo "## Етап 2 доповнення — контакт і --redirects ($(date +%d.%m.%Y))"\x3b   echo\x3b   echo "Заявлено агентом: 94 тести, коміт e209972\x3b URL проєкту в User-Agent дає 0 з 60 помилок 429, без контакту 20 з 30\x3b --redirects none\x3b dry-run за виміряним часом."\x3b   echo '```'\x3b   uv run pytest -q 2>&1 | tail -1\x3b   uv run wiki-interest fetch --spec /tmp/fetch-check.json --dry-run --redirects none 2>/dev/null\x3b   echo '```'\x3b } >> ~/wiki-lab/verification-log.md;4f04693e-1ae4-4357-9e37-482c5d7d8138]633;C
## Етап 2 доповнення — контакт і --redirects (27.09.2026)

Заявлено агентом: 94 тести, коміт e209972; URL проєкту в User-Agent дає 0 з 60 помилок 429, без контакту 20 з 30; --redirects none; dry-run за виміряним часом.
```
94 passed in 13.43s
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","dry_run":true,"range":{"start":"2025-01-01","end":"2026-08-31"},"redirects":"none","series":9,"series_cached":9,"series_skipped":0,"requests_needed":0,"seconds_per_request":0.8,"estimate_basis":"default for this User-Agent (no previous runs in this cache)","estimated_seconds":0,"estimated_minutes":0.0,"missing_articles":[],"unresolved":[]}
```
--- той самий dry-run на порожньому кеші (очікую 5 серій: 3 основні + 2 агрегати; 4 редиректи пропущено) ---
```
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","dry_run":true,"range":{"start":"2025-01-01","end":"2026-08-31"},"redirects":"none","series":2,"series_cached":0,"series_skipped":0,"requests_needed":2,"seconds_per_request":0.8,"estimate_basis":"default for this User-Agent (no previous runs in this cache)","estimated_seconds":2,"estimated_minutes":0.0,"missing_articles":[],"unresolved":[{"where":"target/pt:Regras do xadrez","lang":"pt","qid":null,"title":"Regras do xadrez"}],"note":"1 item/language pairs are not resolved yet; their redirects are unknown, so requests_needed is a lower bound (each article needs at least 3 requests plus resolve). Run `resolve` first for an exact estimate."}
```

Примітка: перший dry-run із --redirects none показав 9 серій, бо всі вже були в кеші з попередньої перевірки; код правильно використовує наявні редиректи, а не відкидає їх.
--- порожній кеш: спершу resolve, потім dry-run --redirects none (очікую 5 серій, 4 пропущено) ---
```
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","result_file":"wiki-interest-out\\resolve_result.json","langs":["pt"],"coverage":{"langs":["pt"],"rows":[{"id":"pt:Regras do xadrez","cells":["redirect_resolved"]}]},"items":[{"id":"pt:Regras do xadrez","status":"resolved","qid":"Q3392263","la
{"ok":true,"tool_version":"0.1.0","data_as_of":"2026-08","dry_run":true,"range":{"start":"2025-01-01","end":"2026-08-31"},"redirects":"none","series":9,"series_cached":0,"series_skipped":4,"requests_needed":5,"seconds_per_request":0.8,"estimate_basis":"default for this User-Agent (no previous runs in this cache)","estimated_seconds":4,"estimated_minutes":0.1,"missing_articles":[],"unresolved":[]}
```

Спостереження: без resolve dry-run дає requests_needed 2, хоча в note сам пише «щонайменше 3 запити на статтю плюс resolve»; нижня межа занижена. Передано агенту.

Висновок:
- pytest: 94 passed.
- --redirects none на порожньому кеші після resolve: 9 серій у специфікації, 4 редиректи пропущено, 5 запитів потрібно (3 основна стаття + 2 агрегати). Працює, як домовлено.
- На заповненому кеші редиректи не відкидаються, а використовуються — коректно.
- estimate_basis чесно вказує, що замірів ще немає.

Розбіжності:
- Моє очікування «series: 5» було хибним: поле рахує всі серії специфікації, а не лише ті, що завантажуються.
- Без resolve нижня межа requests_needed занижена (2 замість щонайменше 6); передано агенту.

## Етап 3 — analyze (27.09.2026)

Заявлено агентом: 123 тести, коміт 40b958a; на реальних даних A: аномальні січень–лютий 2024/2025 знайдено (−32% без них проти −35%), leave-one-out −36…−34%, астрономія проти контролю 1,27 [1,10; 1,44]; B: сплеск 14.04.2025 likely_human, −35% без сплесків проти −47%; metrics.json побайтово відтворюваний, stdout 965 байтів.
```
417d44c Skill draft: SKILL.md and references (to be reconciled with CLI)
40b958a Stage 3: analyze — panels, indices, robustness, spikes, anomalies, confidence
0fb1071 Evals: scenario checklists and trigger queries
123 passed in 36.59s
```
Незалежна перевірка на реальних даних — у фінальному прогоні сценарію A з навичкою.
Примітка: числа не збігаються з доведенням A напряму — інше вікно (12 міс. проти січ–серп) і інший кошик (20 понять проти 33 статей); збігається картина.

## Прогін Haiku 4.5, сценарій A, навичка в пісочниці (діагностичний) — 27.09.2026

Умови: Claude Code desktop, Haiku 4.5, режим Accept edits; навичка скопійована з GitHub у .claude/skills/wiki-interest/ до коміту з новим description. У запиті навичку не згадано.

Що сталося:
- Спершу Haiku навичку не викликала, писала власні скрипти (analyze_astronomy.py, debug_api.py), кілька разів впала на API.
- Потім знайшла й викликала навичку з назвою wiki-interest-skill-501972d9 (не нашу wiki-interest — імовірно тимчасова копія з тесту недовиклику).
- Відкривши навичку, написала «навичка зараз працює, очікую результатів» — вважала, що навичка виконується сама. Жодної команди wiki-interest не запустила.
- Після «продовжуй» створила generate_report.py з вписаними вручну числами (~2 400 переглядів на місяць, «+12–18% (估計)») і висновком «тренд позитивний, додавати курс можна».
- PDF 3,3 КБ: кирилиця — чорні квадрати; у підписі хибне джерело «Wikipedia Pageviews API».

Висновок: відповідь протилежна до реальних даних (analyze: падіння близько −35%). Числа й висновки вигадані й підписані реальним джерелом.

Що закриває: SKILL.md — перше правило «жодних чисел і висновків без виконаних команд; якщо команди не працюють — зупинитися й сказати користувачу»; перше речення тіла — «навичка не виконується сама»; новий description; прибрати тимчасові копії навички.
