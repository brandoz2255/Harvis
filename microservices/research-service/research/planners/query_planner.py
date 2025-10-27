# python_back_end/research/planners/query_planner.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from ..config.settings import get_settings
from ..core.utils import canonicalize_url
from .prompts import (
    SYSTEM_PLANNER,
    DECOMPOSE_PROMPT,
    HYDE_PROMPT,
    QUERIES_FROM_STRUCTURE,
    OPTIMIZE_QUERIES_PROMPT,
)

@dataclass
class PlanOutput:
    queries: List[str]
    debug: Dict[str, str]

class QueryPlanner:
    """
    Plans high-recall, high-precision web queries from a user topic.

    This class expects an LLM client with a `chat(model, messages, timeout_s)` method
    returning a string. We'll wire this up to Ollama later (llm/ollama_client.py).
    """

    def __init__(self, llm_client, model_policy=None, settings=None):
        self.cfg = settings or get_settings()
        self.model_policy = model_policy or self.cfg.model_policy
        self.llm = llm_client

    # ---------- Public API ----------

    def plan_queries(
        self,
        topic: str,
        depth: str = "standard",
        domain_filters: Optional[List[str]] = None,
        date_range: Optional[Tuple[str, str]] = None,
    ) -> PlanOutput:
        """
        Produce a list of optimized queries and a debug dict.

        :param topic: user topic / question
        :param depth: quick | standard | deep (affects budgets later)
        :param domain_filters: if provided, constrain optimization to these domains
        :param date_range: optional ("YYYY-MM-DD","YYYY-MM-DD")—currently used only to hint recency
        """
        topic = topic.strip()
        debug: Dict[str, str] = {}

        # 1) HYDE to mine entities/terms (best-effort)
        hyde = self._try_hyde(topic)
        debug["hyde"] = hyde or ""

        # 2) Decompose into sub-questions/entities/aliases
        subs, ents, aliases, raw_block = self._try_decompose(topic)
        debug["decomposition"] = raw_block or ""

        # 3) Turn that structure into 8 queries (LLM), fallback heuristics if needed
        candidate_queries = self._queries_from_structure(topic, subs, ents, aliases)
        debug["queries_initial"] = "\n".join(candidate_queries)

        # 4) Lightweight optimization pass (add authoritative domains, years)
        optimized = self._optimize_queries(candidate_queries, domain_filters)
        debug["queries_optimized"] = "\n".join(optimized)

        # 5) Expand with simple heuristic variants (short tails) + dedupe
        expanded = self._heuristic_variants(topic, optimized, ents, aliases)
        deduped = self._dedupe_queries(expanded)

        # 6) Trim by depth to a practical count
        target_count = {"quick": 4, "standard": 8, "deep": 12}.get(depth, 8)
        final = deduped[:target_count]
        debug["queries_final"] = "\n".join(final)

        return PlanOutput(queries=final, debug=debug)

    # ---------- Steps ----------

    def _try_hyde(self, topic: str) -> Optional[str]:
        """
        HyDE (Hypothetical Document Embeddings) style: draft a short hypothetical answer
        to surface salient entities/terms. If LLM fails, return None.
        """
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PLANNER},
                {"role": "user", "content": HYDE_PROMPT.format(topic=topic)},
            ]
            return self.llm.chat(self.model_policy.planner, messages, timeout_s=12)
        except Exception:
            return None

    def _try_decompose(self, topic: str) -> Tuple[List[str], List[str], List[str], Optional[str]]:
        """
        Ask LLM to produce sub-questions, entities, aliases.
        Returns (subquestions, entities, aliases, raw_block).
        """
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PLANNER},
                {"role": "user", "content": DECOMPOSE_PROMPT.format(topic=topic)},
            ]
            block = self.llm.chat(self.model_policy.planner, messages, timeout_s=15)
            subs = _extract_bullets(block, header="SUBQUESTIONS:")
            ents = _extract_bullets(block, header="ENTITIES:")
            aliases = _extract_bullets(block, header="ALIASES:")
            return (subs, ents, aliases, block)
        except Exception:
            # Fallback heuristics
            subs = self._fallback_subquestions(topic)
            ents = self._fallback_entities(topic)
            aliases = []
            return (subs, ents, aliases, None)

    def _queries_from_structure(self, topic: str, subs: List[str], ents: List[str], aliases: List[str]) -> List[str]:
        """
        Ask LLM to turn structure into 8 diverse queries; fallback if needed.
        """
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PLANNER},
                {"role": "user", "content": QUERIES_FROM_STRUCTURE.format(
                    topic=topic,
                    bullets_subquestions="\n".join(f"- {s}" for s in subs[:6]),
                    bullets_entities="\n".join(f"- {e}" for e in ents[:10]),
                    bullets_aliases="\n".join(f"- {a}" for a in aliases[:10]) or "-",
                )},
            ]
            text = self.llm.chat(self.model_policy.planner, messages, timeout_s=15)
            queries = [q.strip().strip("-•0123456789. ").strip('"\'') for q in text.splitlines() if q.strip()]
            return [q for q in queries if len(q) > 4][:12] or self._fallback_queries(topic, subs, ents)
        except Exception:
            return self._fallback_queries(topic, subs, ents)

    def _optimize_queries(self, queries: List[str], domain_filters: Optional[List[str]]) -> List[str]:
        """
        LLM-assisted mini-optimization: add site filters and year markers without killing diversity.
        """
        auth = ", ".join(self.cfg.authority_domains)
        years = ", ".join(self.cfg.recency_markers)
        doms = ", ".join(domain_filters) if domain_filters else "None"

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PLANNER},
                {"role": "user", "content": OPTIMIZE_QUERIES_PROMPT.format(
                    authority_domains=auth,
                    recency_markers=years,
                    domain_filters=doms,
                    queries="\n".join(queries),
                )},
            ]
            text = self.llm.chat(self.model_policy.planner, messages, timeout_s=10)
            out = [q.strip().strip("-•0123456789. ").strip('"\'') for q in text.splitlines() if q.strip()]
            # Keep same count; fallback to input on failure
            if len(out) >= max(1, len(queries) - 2):
                return out[:len(queries)]
            return queries
        except Exception:
            return queries

    # ---------- Heuristics & Helpers ----------

    def _heuristic_variants(self, topic: str, queries: List[str], ents: List[str], aliases: List[str]) -> List[str]:
        """
        Add a few lightweight variants: quoted phrases, filetype/pdf, intitle.
        Keep input first to preserve LLM-crafted diversity.
        """
        variants = list(queries)
        tail = []

        # add 2-3 pdf/arxiv variants if technical
        if _looks_technical(topic) or any(_looks_technical(q) for q in queries):
            for q in queries[:3]:
                tail.append(f'{q} filetype:pdf')
            tail.append(f'{topic} site:arxiv.org OR site:ieee.org')

        # add alias/entity quoted variants
        for term in (ents[:2] + aliases[:2]):
            if len(term.split()) >= 2:
                tail.append(f'"{term}" {topic}')
            else:
                tail.append(f'{topic} {term}')

        # intitle variants
        for q in queries[:2]:
            tail.append(f'intitle:"{_first_keywords(topic)}" {q}')

        variants.extend(tail)
        return variants

    def _dedupe_queries(self, queries: List[str]) -> List[str]:
        seen = set()
        out = []
        for q in queries:
            k = _normalize_query(q)
            if k not in seen:
                seen.add(k)
                out.append(q.strip())
        return out

    def _fallback_subquestions(self, topic: str) -> List[str]:
        base = [
            f"What is {topic} trying to address?",
            f"What are the main methods/approaches for {topic}?",
            f"What recent developments (last 1-2 years) exist for {topic}?",
            f"What are comparisons/benchmarks relevant to {topic}?",
            f"What are the best practices and pitfalls for {topic}?",
        ]
        return base

    def _fallback_entities(self, topic: str) -> List[str]:
        ents = []
        # naive hints for AI/ML
        if _looks_technical(topic):
            ents.extend(["arXiv", "GitHub", "Hugging Face"])
        return ents

    def _fallback_queries(self, topic: str, subs: List[str], ents: List[str]) -> List[str]:
        out = [topic]
        if _looks_technical(topic):
            out.append(f"{topic} site:arxiv.org OR site:huggingface.co OR site:github.com 2024 OR 2025")
            out.append(f"{topic} tutorial guide documentation")
            if ents:
                out.append(f"{topic} {' OR '.join(ents[:3])}")
        else:
            out.append(f"{topic} review analysis 2024 OR 2025")
            out.append(f"{topic} pdf site:.edu OR site:.gov")
        return out[:8]

# ---------- small helpers ----------

def _extract_bullets(text: str, header: str) -> List[str]:
    """
    Parse bullet lists under a header label from an LLM response.
    """
    lines = text.splitlines()
    items: List[str] = []
    mode = False
    for ln in lines:
        if ln.strip().upper().startswith(header):
            mode = True
            continue
        if mode:
            if not ln.strip():
                # stop on blank line after we've started
                if items:
                    break
                else:
                    continue
            if ln.strip().startswith(("-", "•", "*")):
                item = ln.strip().lstrip("-•*").strip()
                if item:
                    items.append(item)
            else:
                # stop if section changes
                if items:
                    break
    return items

def _looks_technical(text: str) -> bool:
    t = text.lower()
    tech_terms = [
        "ai", "ml", "llm", "model", "neural", "python", "api",
        "database", "embedding", "transformer", "agent", "research", "paper"
    ]
    return any(w in t for w in tech_terms)

def _normalize_query(q: str) -> str:
    # strip trivial differences for dedupe
    q = q.lower().strip()
    q = " ".join(q.split())
    for tok in ["(", ")", '"', "'"]:
        q = q.replace(tok, "")
    return q

def _first_keywords(topic: str) -> str:
    # pick a couple meaningful words for intitle usage
    words = [w for w in topic.split() if len(w) > 3][:3]
    return " ".join(words) or topic[:12]

