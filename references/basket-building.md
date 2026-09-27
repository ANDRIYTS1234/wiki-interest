# Building a basket

## Why a basket

In testing without this skill, conclusions drawn from one article were wrong in two of three cases: the head article of a topic ("Chess") fell much faster than the rest of the topic, and a single substitute article made one language look worse than it was. A basket of related articles, identical across languages, gives a fair picture.

## How to choose items

- Start with the core concept, then add 5–20 subtopics a learner or customer of the product would read: for a course — basics, rules, techniques, key people, tools; for a diet app — the diet, related diets, underlying physiology, weight loss.
- Use Wikidata items (`qid`) so the same concept is compared across languages. Get QIDs by resolving `{"query": ..., "query_lang": ...}` items.
- Group items when the product question is about a sub-audience: `"group": "learning"` vs `"group": "players"`. Metrics are computed per group too.
- Exclude with a reason when a concept is ambiguous or broader than the topic: `"exclude": "not only chess"`. Excluded items are listed in the appendix.
- The CLI builds the **panel** automatically: only articles that existed and had views before the base period, present in all compared languages. Articles created later (a new star player, a new app) cannot create fake growth. If the panel has fewer than 5 articles you get `PANEL_SMALL`.
- Proxies (`{"lang": "pl", "title": "...", "proxy_for": "Q..."}`) are shown separately and never used in cross-language comparison.
- Add a `control` basket (a comparable neutral topic) when the user asks "can we trust this growth?".

## analysis.json

```json
{
  "question": "Is interest in astronomy growing in Ukrainian Wikipedia?",
  "langs": ["uk"],
  "window": {"months": 12, "end": "latest"},
  "history_start": "2016-01",
  "baselines": [2019, 2021],
  "baskets": [
    {"id": "target", "role": "target", "label": "Astronomy",
     "items": [{"qid": "Q333"}, {"qid": "Q544", "group": "solar_system"}]},
    {"id": "control", "role": "control", "label": "Other natural sciences",
     "items": [{"qid": "Q413"}, {"qid": "Q2329"}]}
  ]
}
```

- `window.end`: `"latest"` or `"YYYY-MM"`. `window.months`: 12 by default; use 24 for "last two years".
- `baselines`: calendar years to compare against in addition to the previous year. 2019 = last pre-COVID year; note that bot classification only exists from May 2020.
- Keep one spec file per question; for follow-ups edit it and rerun.
