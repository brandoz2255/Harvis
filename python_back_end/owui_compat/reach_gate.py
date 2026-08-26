"""When should plain chat go and look something up, and what should it look up?

``chat_reach`` could always fetch. The whole question is *when*, and the old
answer was two narrow regexes in ``workspace_bridge``: an explicit fetch
imperative, or a freshness word inside a question. Measured against 292 real
user turns from this account, that fired on 13 of them (4.5%) — and it missed
the turn that motivated this module:

    "show me benchmarks of fable gpt 5.5 sol and you and compare"

No imperative, no freshness word, so no search ran at all and the model answered
about a product it had never heard of. The turn after it said "use a web search
if you dont know anything", which *did* match — and then searched that literal
sentence, returning a 2010 blog post called "Google search: you don't know
anything", a Pinterest board, and India's eCourts portal. Both halves of this
module exist because of that pair: the gate was too narrow, and the query was
the raw user turn.

Three layers, cheapest first:

1. **Exclusions** — an artifact verb ("write a function…"), arithmetic, or a
   short chatty line never searches. These are checked *before* anything else
   because they are what keeps the widened gate from firing on ordinary work.
2. **Regex fast-path** — an explicit imperative, a freshness word, or a specific
   named entity/version inside a question. Zero added latency, and on the 292
   real turns this lands 16 (5.5%) with one false positive.
3. **Classifier fallback** — for the ambiguous middle the regex cannot call: a
   plain lowercase question with no capitalised name and no version number, like
   "who is the ceo of anthropic". One short call to the model already answering
   the turn, which returns both the yes/no *and* the search query.

The regex ceiling is real and worth stating: this user types lowercase, so
proper-noun detection cannot see "anthropic" or "lakers". That is precisely the
gap layer 3 fills, and precisely why layer 3 is not optional decoration.

Everything here is advisory. A failed classifier call, a missing route, a
malformed reply — all fall back to the regex verdict, and the turn answers as it
did before.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# Reuse the two patterns that already earned their place, rather than forking
# them — workspace_bridge still routes on the narrow definition and the two must
# not drift apart.
from .workspace_bridge import (  # noqa: E402
    _ARTIFACT_VERB_RE,
    _FRESHNESS_RE,
    _REACH_IMPERATIVE_RE,
)

# ── Layer 2: entity detection ────────────────────────────────────────────────
# A version-bearing token is the strongest signal available in lowercase text:
# "gpt 5.5", "postgres 18", "qwen3:4b", "python3.13". The negative lookahead is
# load-bearing — without it "does 5 mean" and "with 2 files" both read as
# products. The stop list was tuned against the real turns; dropping it took the
# false-positive rate from 1/14 to 6/14.
_STOP = (
    r"(?:does|did|need|needs|mean|means|take|with|that|this|from|have|has|been|"
    r"were|was|will|when|then|than|about|there|here|they|them|your|just|like|"
    r"only|also|some|more|most|into|over|under|give|want|know|make|made|used|"
    r"using|line|lines|file|files|step|steps|part|parts|time|times|page|pages|"
    r"exactly|around|roughly|approximately|least|maximum|minimum|max|min|within|"
    r"top|first|last|next|another|these|those|each|every|both|all|any)"
)
# Nouns that turn a number into a length constraint rather than a version.
# "explain photosynthesis in exactly 4 sentences" read as a product called
# "exactly 4" and searched the web for an essay-length instruction.
_COUNT_NOUN = (
    r"(?:sentences?|words?|lines?|items?|paragraphs?|bullets?|points?|steps?|"
    r"examples?|ways?|reasons?|options?|things?|times?|files?|characters?|chars?|"
    r"tokens?|minutes?|seconds?|hours?|days?|weeks?|months?|years?|people|others?)"
)
_VERSIONED_RE = re.compile(
    # qwen3, gpt-5, k2.5, python3.13 — a letter run with a digit welded on
    r"\b[a-z][a-z]*\d[\w.\-]*\b"
    # gpt-5.5, claude-4, node:22 — separated by a hyphen, dot or colon
    r"|\b[a-z][a-z]*[-.:]\d[\w.\-]*\b"
    # "fable 5", "postgres 18" — a word then a bare number, minus the stop list
    rf"|\b(?!{_STOP}\b)[a-z][a-z\-]{{2,}}\s+\d+(?:\.\d+)?\b(?!\s*{_COUNT_NOUN}\b)",
    re.IGNORECASE,
)
# Two or more capitalised words in a row: "Monty Hall", "Golden State Warriors".
# One capitalised word is not enough — it matches every sentence opener.
_PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}(\s+[A-Z][a-z]{2,})+\b")
# A quoted phrase is the user pointing at a specific string.
_QUOTED_RE = re.compile(r"[\"“']([^\"”']{4,60})[\"”']")

# ── Layer 1: exclusions ──────────────────────────────────────────────────────
# "what is 47 times 12" is a question with a number in it and nothing to look up.
_ARITH_RE = re.compile(
    r"\b\d+\s*(plus|minus|times|divided\s+by|\+|-|\*|/|x)\s*\d+\b", re.IGNORECASE
)

# ── The ask shape ────────────────────────────────────────────────────────────
# Wider than workspace_bridge's _QUESTION_RE, because that one only ever ran
# with a freshness word beside it. Here it also has to catch "compare X and Y"
# and "benchmarks for Z", which are information requests in the indicative mood.
_ASK_RE = re.compile(
    r"\?"
    r"|^\s*(what|whats|who|whos|when|where|which|why|how|is|are|does|did|has|have|any)\b"
    r"|\b(give|tell|show|get|find|fetch|explain)\s+(me|us)\b"
    r"|^\s*(list|find|look\s+up|explain|compare|research|info\s+on|details\s+on)\b"
    r"|\b(compare|benchmarks?|news|release[ds]?|announced|pricing|specs?)\b",
    re.IGNORECASE,
)

_MAX_CLASSIFIER_WORDS = 60   # past this it is a paste or a spec, not a lookup


def _entityish(text: str) -> bool:
    """True when the turn names something specific enough to be worth fetching."""
    return bool(
        _VERSIONED_RE.search(text)
        or _PROPER_RE.search(text)
        or _QUOTED_RE.search(text)
    )


def _chatty(text: str) -> bool:
    """A short line with no question mark and nothing named — "thanks", "ok cool"."""
    return len(text.split()) < 6 and "?" not in text and not _entityish(text)


def verdict(message: str) -> str:
    """``"yes"`` | ``"maybe"`` | ``"no"`` — should this turn be grounded?

    ``"maybe"`` means the regex genuinely cannot tell and a classifier call is
    worth its latency. It is deliberately reachable only from an ask-shaped,
    non-excluded, reasonably short turn, so ordinary chat never pays for it.
    """
    m = (message or "").strip()
    if not m:
        return "no"
    # Explicit instruction outranks every exclusion below: "search the web and
    # write me a script" still searches, even though it has an artifact verb.
    if _REACH_IMPERATIVE_RE.search(m):
        return "yes"
    # Something has to EXIST when this turn is done. A sandbox owns that, and
    # this is the single check that keeps the widened gate off ordinary work:
    # without it, proper-noun detection alone fired on 10 real turns and every
    # one of them was a build request.
    if _ARTIFACT_VERB_RE.search(m):
        return "no"
    if _ARITH_RE.search(m):
        return "no"
    if _chatty(m):
        return "no"
    # "what's the latest X" — freshness alone is enough now. Paired with the
    # artifact-verb exclusion above it no longer catches "run the latest
    # migration", which is what forced the old rule to also demand a question.
    if _FRESHNESS_RE.search(m):
        return "yes"
    if not _ASK_RE.search(m):
        return "no"
    if _entityish(m):
        return "yes"
    if len(m.split()) > _MAX_CLASSIFIER_WORDS:
        return "no"
    return "maybe"


def needs_reach(message: str) -> bool:
    """Regex-only verdict, for callers with no model to fall back on."""
    return verdict(message) == "yes"


# ── Query derivation ─────────────────────────────────────────────────────────

_QUERY_STOPWORDS = frozenset("""
a an the and or but if of for to in on at by with from as is are was were be been
being do does did doing done have has had having i you he she it we they me him
her us them my your his its our their this that these those what which who whom
whose when where why how not no nor so than then too very can could will would
shall should may might must ok okay yes yeah please just also about into over
under again more most some any each few other such only own same s t don dont
use using used know knows anything something nothing thing things get got give
gives tell tells show shows find finds look looks make makes want wants need
needs go goes going come comes say says see sees think thinks
""".split())


def _content_words(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z0-9][a-z0-9.\-:]*", (text or "").lower())
        if w not in _QUERY_STOPWORDS and len(w) > 1
    ]


def fallback_query(message: str, previous: str = "") -> str:
    """A search query derived from the turn, with no model call.

    The bug this fixes: a meta-instruction like "use a web search if you dont
    know anything" was passed to the search engine verbatim, which returned a
    2010 blog post with that phrase in its title. Stripping the imperative
    leaves "use a if you dont know anything" — nothing but stopwords — and that
    emptiness is exactly the signal that the real subject is in the *previous*
    turn.
    """
    m = (message or "").strip()
    if not m:
        return (previous or "").strip()[:300]
    stripped = _REACH_IMPERATIVE_RE.sub(" ", m).strip()
    if len(_content_words(stripped)) < 2:
        prev = (previous or "").strip()
        if len(_content_words(prev)) >= 2:
            return prev[:300]
        return m[:300]
    stripped = re.sub(r"^\s*(?:for|about|on|of|regarding|re)\b\s*", "", stripped, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", stripped).strip()[:300]


_CLASSIFIER_SYSTEM = (
    "You decide whether an assistant should run a web search before answering, "
    "and if so, what to search for.\n"
    "Answer SEARCH when the turn asks about a specific named thing (a product, "
    "version, person, company, place, team, event, paper, repository), anything "
    "current or recent, prices, benchmarks, news, releases, or any fact you are "
    "not certain of.\n"
    "Answer NO_SEARCH for small talk, opinions, arithmetic, general explanations "
    "of stable concepts, and anything about the user's own code or files.\n"
    'Reply with JSON only, no prose: {"search": true, "query": "..."} or '
    '{"search": false}.\n'
    "The query must be what you would actually type into a search engine — the "
    "subject itself, never the user's instruction to search. If the turn says "
    'something like "look it up if you are not sure", the subject is in the '
    "PREVIOUS message, so search for that instead."
)


def _parse_classifier(raw: str) -> dict | None:
    """Pull the JSON object out of a reply that may be wrapped in prose or fences."""
    text = (raw or "").strip()
    if not text:
        return None
    # Reasoning models emit a think block; a chatty one emits ```json fences.
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "search": bool(data.get("search")),
        "query": str(data.get("query") or "").strip()[:300],
    }


def classifier_model(picked: str) -> str:
    """Which model answers the gate question.

    Defaults to the model already answering the turn, because that one is
    routable by construction — a hardcoded local tag would 404 for anyone whose
    ``openclaw_llm_config`` points at a cloud provider. ``HARVIS_REACH_CLASSIFIER_MODEL``
    overrides it with something small and local when the box has one.
    """
    return (os.getenv("HARVIS_REACH_CLASSIFIER_MODEL") or "").strip() or picked


async def classify(
    message: str,
    previous: str,
    model_name: str,
    *,
    pool=None,
    user_id: int | None = None,
    timeout: float = 20.0,
) -> dict | None:
    """``{"search": bool, "query": str}``, or ``None`` when unavailable.

    ``None`` is not "no" — it means the caller should keep its regex verdict.
    """
    model = classifier_model(model_name)
    if not model:
        return None
    try:
        from workspace.orchestration.model_router import ModelRouter

        user = f"Current message: {message.strip()[:800]}"
        if previous:
            user = f"Previous message: {previous.strip()[:400]}\n{user}"
        msg = await ModelRouter().complete(
            model_name=model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=600,   # reasoning models spend most of this before any text
            timeout=timeout,
            pool=pool,
            user_id=user_id,
        )
    except Exception:
        logger.info("reach_gate: classifier unavailable for %r", message[:60], exc_info=True)
        return None
    parsed = _parse_classifier(str(msg.get("content") or ""))
    if parsed is None:
        logger.info("reach_gate: classifier reply unparsable for %r", message[:60])
    return parsed


# ── Relevance ────────────────────────────────────────────────────────────────

def looks_relevant(query: str, results: list[dict]) -> bool:
    """Do the search results have anything to do with what was asked?

    The Fable 5 turn read three perfectly fetchable pages that were about
    nothing. Because they were *readable*, the rescue model round never fired —
    it only triggered on an empty read. This is the check that distinguishes
    "nothing came back" from "junk came back", which is the more common failure
    once a query is even slightly off.

    Lenient on purpose: one third of the content words present is enough. It is
    there to catch total misses, not to second-guess a search engine.
    """
    wanted = set(_content_words(query))
    if not wanted or not results:
        return True   # nothing to judge against; do not manufacture a verdict
    haystack = " ".join(
        f"{r.get('title', '')} {r.get('snippet', '')} {r.get('url', '')}"
        for r in results
    ).lower()
    hits = sum(1 for w in wanted if w in haystack)
    return hits / len(wanted) >= 0.34


# ── Query repair ─────────────────────────────────────────────────────────────
# The corrective half of the loop in ``chat_reach``: when a search comes back
# empty or off-topic, these say what to type instead. Deterministic first for
# the same reason the search itself is — a rewrite that needs no model works on
# every lane, and costs nothing to try before spending a round-trip.

def page_coverage(query: str, pages: list[dict]) -> float:
    """Fraction of the query's content words that appear in the fetched text.

    ``looks_relevant`` grades *snippets*, which a search engine wrote to look
    like a match. This grades what the page actually says, which is the thing
    the answer will be built from. A page that ranked first and then turns out
    to be a listing, a paywall stub, or a cookie wall scores near zero here and
    near one there.
    """
    wanted = set(_content_words(query))
    if not wanted or not pages:
        return 0.0
    haystack = " ".join((p.get("text") or "") for p in pages).lower()
    if not haystack.strip():
        return 0.0
    return sum(1 for w in wanted if w in haystack) / len(wanted)


def _distinctive(query: str, n: int = 2) -> list[str]:
    """The ``n`` words that make this query specific rather than generic.

    Length as a proxy for specificity — the same proxy ``broader_query`` uses,
    and for the same reason: with no corpus to count against, the long words in
    a query are usually the product names and technical terms while the short
    ones are connective tissue. It is only a tie-breaker. It is NOT how the
    grader decides what matters — ``missing_terms`` does that, because length
    gets this wrong in exactly the case that matters most: a made-up eight-letter
    product name ranks below the word "configuration".
    """
    words = _content_words(query)
    return sorted(sorted(set(words), key=words.index), key=len, reverse=True)[:n]


def missing_terms(query: str, results: list[dict], pages: list[dict]) -> list[str]:
    """Query words that appear NOWHERE in what the search came back with.

    This is the grader's real signal, and it comes free: the search engine has
    already told us which words it could match. A word that survives ranking,
    five titles, five snippets and every page fetched is a word nothing on the
    web associates with this subject — which means the search found something
    else, no matter how relevant the snippets look.

    Measured on live searches: three genuinely answerable queries returned an
    empty list here and 1.00 page coverage, while two queries carrying an
    invented product name returned the invented name and scored 0.50–0.60. That
    gap is the whole check. Coverage alone graded both sides the same way,
    because "gateway", "policy" and "configuration" are on every page ever
    written and the two words naming the subject were the two that were gone.
    """
    words = list(dict.fromkeys(_content_words(query)))
    if not words:
        return []
    haystack = " ".join(
        f"{r.get('title', '')} {r.get('snippet', '')} {r.get('url', '')}"
        for r in results
    )
    haystack += " " + " ".join((p.get("text") or "") for p in pages)
    haystack = haystack.lower()
    if not haystack.strip():
        return []   # nothing fetched at all is "empty", judged elsewhere
    return [w for w in words if w not in haystack]


def narrower_query(query: str, message: str = "", focus: str = "") -> str | None:
    """Pin the search to the entity that was actually asked about, or ``None``.

    For the "readable but about nothing" failure. A bare word sequence lets the
    engine match any of the words; quoting the distinguishing phrase makes it
    match the thing. Order of preference is how specific each signal is: the
    ``focus`` word the grader saw the engine drop, then an explicitly quoted
    phrase, then a version-bearing token, then a run of proper nouns. Returns
    ``None`` when there is no such entity, or when the query
    already quotes one — repeating a rewrite that has already been tried is how
    a self-correcting loop turns into a stuck one.
    """
    if '"' in query:
        return None
    source = f"{query} {message}".strip()
    entity = ""
    if focus:
        # The grader already found the word the engine dropped. Quoting exactly
        # that is a better repair than re-deriving a guess from the phrasing —
        # and when the quoted search then comes back empty, that is the honest
        # answer to the question, not a failure of the loop.
        for m in re.finditer(rf"\b\S*{re.escape(focus)}\S*\b", source, re.IGNORECASE):
            entity = m.group(0).strip(".,:;!?")
            break
    quoted = _QUOTED_RE.search(source) if not entity else None
    if quoted:
        entity = quoted.group(1).strip()
    if not entity:
        versioned = _VERSIONED_RE.search(source)
        if versioned:
            entity = versioned.group(0).strip()
    if not entity:
        proper = _PROPER_RE.search(source)
        if proper:
            entity = proper.group(0).strip()
    if not entity or len(entity) < 3:
        return None
    rest = [w for w in _content_words(query) if w not in entity.lower()]
    return f'"{entity}" {" ".join(rest[:6])}'.strip()[:300]


def broader_query(query: str) -> str | None:
    """Drop the narrowest terms, or ``None`` when there is nothing left to drop.

    For the opposite failure: zero results, which usually means the query
    carried a phrase no page contains verbatim. Longer words are the specific
    ones — a model number, a full product name — so keeping those and dropping
    the short connective ones widens the net without losing the subject.
    """
    words = _content_words(query)
    if len(words) <= 3:
        return None
    kept = sorted(_distinctive(query, 3), key=words.index)
    out = " ".join(kept)
    return out if out and out != query.strip().lower() else None


_REFINE_SYSTEM = (
    "You repair failing web searches. You are given the user's question, the "
    "queries already tried, and the titles those queries returned. The results "
    "did not answer the question.\n"
    "Write ONE different query that would. Change the terms — do not reword the "
    "same search. Use the names, versions and technical terms a page that "
    "answers this would actually contain.\n"
    'Reply with JSON only, no prose: {"query": "..."}'
)


def _parse_refine(raw: str) -> str:
    text = re.sub(r"<think>.*?</think>", " ", raw or "", flags=re.DOTALL | re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return ""
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("query") or "").strip()[:300]


async def refine_query(
    message: str,
    tried: list[str],
    results: list[dict],
    model_name: str,
    *,
    pool=None,
    user_id: int | None = None,
    timeout: float = 20.0,
) -> str:
    """A model-written replacement query, or ``""`` when unavailable.

    Only reached when both deterministic rewrites declined, so the cost is paid
    on the turns that actually need it. Every failure mode — no route, a
    timeout, an unparsable reply, a query the loop has already run — comes back
    as ``""`` and ends the loop with whatever it has, which is never worse than
    the one-shot search this replaced.
    """
    model = classifier_model(model_name)
    if not model:
        return ""
    seen = ", ".join(repr(q) for q in tried[-3:])
    titles = "\n".join(
        f"- {(r.get('title') or r.get('url') or '')[:120]}" for r in results[:6]
    ) or "(no results at all)"
    try:
        from workspace.orchestration.model_router import ModelRouter

        msg = await ModelRouter().complete(
            model_name=model,
            messages=[
                {"role": "system", "content": _REFINE_SYSTEM},
                {"role": "user", "content": (
                    f"Question: {message.strip()[:600]}\n"
                    f"Queries already tried: {seen}\n"
                    f"Titles they returned:\n{titles}"
                )},
            ],
            temperature=0.2,
            max_tokens=600,
            timeout=timeout,
            pool=pool,
            user_id=user_id,
        )
    except Exception:
        logger.info("reach_gate: refine unavailable for %r", message[:60], exc_info=True)
        return ""
    out = _parse_refine(str(msg.get("content") or ""))
    if out and out.strip().lower() in {q.strip().lower() for q in tried}:
        return ""
    return out


# ── Hedge detection ──────────────────────────────────────────────────────────
# Only KNOWLEDGE hedges. "I don't have access to your files" is a capability
# statement and searching the web for it would be nonsense, so the patterns all
# require an information noun or an explicit training-cutoff phrase.
_HEDGE_RE = re.compile(
    r"i (?:don'?t|do not) have (?:any |much |specific |detailed )?"
    r"(?:information|knowledge|data|details|record|records|context)\b"
    r"|i (?:have|hold) no (?:information|knowledge|record|records|data)\b"
    r"|i'?m not (?:aware|familiar) (?:of|with)\b"
    r"|i am not (?:aware|familiar) (?:of|with)\b"
    r"|(?:as of|up to|prior to) my (?:last )?(?:knowledge|training)"
    r"\s*(?:cut[-\s]?off|update|data)?\b"
    r"|my (?:knowledge|training data|training)\s*(?:cut[-\s]?off)?\s*"
    r"(?:only )?(?:goes|extends|runs|is current) (?:up )?to\b"
    r"|my (?:knowledge|training)[-\s]?(?:data )?cut[-\s]?off\b"
    r"|i (?:can'?t|cannot|could not|couldn'?t) find any "
    r"(?:information|reference|references|record|records)\b"
    r"|(?:there (?:is|'s) no|i (?:know|see) of no) (?:widely[- ])?"
    r"(?:known|recognized|recognised|documented|established|public)\b"
    r"|(?:doesn'?t|does not) (?:appear|seem) to (?:be|exist) "
    r"(?:a |an |any )?(?:widely[- ])?(?:known|recognized|recognised|documented|real)\b"
    r"|i'?m not sure (?:what|who|which)\b"
    r"|(?:is|are) not something i(?:'m| am)? (?:aware|familiar)\b",
    re.IGNORECASE,
)
# A hedge buried on page three of a long answer is an aside, not a failure to
# answer. The real thing shows up in the opening.
_HEDGE_WINDOW = 1_500


def detect_hedge(answer: str) -> bool:
    """True when the model said, in the opening, that it does not know this."""
    return bool(_HEDGE_RE.search((answer or "")[:_HEDGE_WINDOW]))
