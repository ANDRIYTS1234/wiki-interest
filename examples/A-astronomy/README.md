# Example A: astronomy in uk.wikipedia (reference spec, no offline snapshot)

`analysis.json` is the scenario A question: 20 astronomy items (target) and 10 other
natural-science items (control), given by Wikidata QID so that disambiguation pages such as
uk «Марс» can never enter the basket. These are the QIDs used and verified against the live APIs
during stage 3.

There is no cache snapshot here: the baskets need a few minutes of live fetch, too large for the
repository. Run it with network access:

```bash
wiki-interest fetch --spec examples/A-astronomy/analysis.json --dry-run
wiki-interest fetch --spec examples/A-astronomy/analysis.json
wiki-interest analyze --spec examples/A-astronomy/analysis.json
```

`window.end` is fixed at 2026-08 so that results are comparable with the stage 3 check; use
`"latest"` for current data.
