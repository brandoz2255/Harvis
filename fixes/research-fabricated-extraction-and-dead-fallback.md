# Deep research: one stage still invents its sources, and the extraction fallback cannot run

**Status:** diagnosed 2026-08-05, **not fixed**. Nothing here has been applied.
**Missing input:** the reported symptom. "Fix the deep research stuff" was the whole brief, so the
two defects below are what a code read found — not a confirmation that either is what was hit.
Both are real and verified present in the tree; which one produced the observed behaviour is open.

Prior context: the 2026-07-24 pass (`docs/handoffs/2026-07-24-research-pipeline-never-ran.md`,
commits `1d140c41` + `e272ac14`) fixed six stacked silent-success defects in this subsystem. These
two survived it.

---

## Defect 1 — `_extraction_stage` fabricates the content it "extracted"

`python_back_end/research/pipeline/research_agent.py:229-258`

```python
async def _extraction_stage(self, search_results: List[Dict]) -> List[Dict]:
    """Extract content from search results (placeholder for your extraction router)"""
    # This will integrate with your ExtractionRouter once ready
    for result in search_results:
        # Simulate content extraction
        content = f"""
        Title: {result['title']}

        This is the extracted content for {result['title']}.
        It contains detailed information about the topic with multiple paragraphs
        of relevant content that would be useful for research synthesis.
        ...
```

Nothing is fetched. Every "source" becomes the same paragraph of invented prose with the page title
interpolated into it, and that is what the ranking, synthesis and verification stages then work on.
The output is an answer built from text that no page ever contained, presented with real URLs
attached to it.

**It is reachable.** `research()` — the class's public entry point at `:363` — calls it at `:413`,
and the object is constructed in production:

- `agent_research.py:33-39` builds the module-level singleton with `enable_advanced_features=True`
- `research/enhanced_research_agent.py:82` then constructs `AdvancedResearchAgent` as
  `self.advanced_agent`
- `research/pipeline/fact_check.py:70` and `pipeline/compare.py` each construct their own instance

So `/api/fact-check` and `/api/comparative-research` go through this class by definition, and
`/api/research-chat` reaches it whenever a request routes to the advanced lane. The legacy lane
(`research/research_agent.py`, used by mic-chat via `use_advanced=False`) does not.

**What tracing this needs:** confirm which lane the failing request actually took before changing
anything. `_run_stage` logs each stage; a real request's log tells you whether `EXTRACTION` ran here
or in `research/extract/router.py`, which is the real extractor and does fetch pages.

The honest fix is to call `research/extract/router.py::extract_html` — which exists, works, and is
what the docstring's "your ExtractionRouter" refers to — rather than to improve the fake text. A
stage that cannot extract should fail loudly; it should never return success with invented content.

---

## Defect 2 — the HTML extraction fallback raises instead of falling back

`python_back_end/research/extract/html_trafilatura.py`

Three problems stacked on one function:

```python
:16   from readablity import Document          # typo — the module is `readability`
:62   return HtmlExtractionResult(title="", test="", language=None, meta={})   # `test=`, not `text=`
:88   if not res.text: res = readablity_fallback(html)
```

1. **`readablity` is a typo** for `readability` (from the `readability-lxml` package). The import is
   wrapped in `try/except`, so `Document` is silently set to `None` on every start.
2. **The package is not declared anywhere.** `python_back_end/requirements-core.txt` pins `ddgs`,
   `newspaper3k`, `lxml_html_clean` and `trafilatura>=1.6.0` — no readability under either spelling.
   Verified in the running container: `trafilatura` 2.1.0 imports fine, `readability` and
   `readablity` both `ModuleNotFoundError`. So fixing only the typo would still leave it dead.
3. **The `Document is None` branch is itself broken.** Line 62 passes `test=""` to a dataclass whose
   field is `text`, and it sits *before* the function's `try`, so the `TypeError` propagates out of
   `readablity_fallback` rather than being caught and degraded.

Net effect: the fallback path can only ever raise. It fires at `:88` when trafilatura returns no
text — paywalled pages, JavaScript-rendered pages, PDFs — which is exactly the case it exists to
handle. The primary extractor works, so this is invisible until a page trafilatura cannot parse
comes back, and then it is an exception rather than a degraded result.

Fixing it means all three: add `readability-lxml` to `requirements-core.txt`, correct the import
name at `:16`, and correct `test=` to `text=` at `:62`. Doing any one alone leaves it dead.

---

## Not a defect — a scan false positive worth recording

`research/llm/ollama_client.py:141` still contains the string `"Response to '"`. **It is inside a
comment** explaining the stub that used to live there and was removed on 07-24. A pattern scan for
the old fabrication will hit this line; the code below it calls the real `/api/generate`. Do not
re-fix it.

---

## What to do first

Ask for the symptom. Which endpoint, what was asked, and what came back wrong — an answer that cited
real URLs but described things they do not say points at defect 1; an exception or an empty result
on a specific site points at defect 2. The two need different fixes, and guessing between them costs
more than asking.

---

## Related

- `docs/handoffs/2026-07-24-research-pipeline-never-ran.md` — the six defects already closed
- `research/extract/router.py:107` — the working extractor `_extraction_stage` should be calling
- The pipeline lane and the legacy lane are separate implementations of the same feature; that
  duplication is why a fix can land in one and leave the other lying.
