# Example A: astronomy in uk.wikipedia (reference spec, no offline snapshot)

`analysis.json` is the scenario A question: 30 astronomy items (target) and 10 other
natural-science items (control), given by Wikidata QID so that disambiguation pages such as
uk «Марс» can never enter the basket.

There is no cache snapshot here: the baskets need ~190 series (~4 minutes of live fetch), too
large for the repository. Run it with network access:

```bash
wiki-interest fetch --spec examples/A-astronomy/analysis.json --dry-run
wiki-interest fetch --spec examples/A-astronomy/analysis.json
wiki-interest analyze --spec examples/A-astronomy/analysis.json
```

The QIDs were assembled without network access to Wikidata. `fetch` resolves them on the fly; check
the article titles in the basket composition of `appendix.md` before trusting the result; a QID that points at the wrong entity shows
up there as an unexpected title.
