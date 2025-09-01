# python_back_end/research/planners/prompts.py

SYSTEM_PLANNER = """You are a senior research strategist.
Your job is to plan web search queries that maximize recall and precision for an LLM-based research pipeline.

Rules:
- Prefer authoritative domains for technical topics.
- Generate diverse queries that cover sub-questions, synonyms, and named entities.
- If the user intent suggests fresh info, bias toward recent years.
- Avoid generic or low-signal terms (e.g., 'what is', 'meaning of').
- Do not include explanations unless requested. Output as plain text lists where asked.
"""

# Decompose the task and produce sub-questions + entities (multi-hop)
DECOMPOSE_PROMPT = """User topic:
{topic}

Task:
1) Identify the key sub-questions that must be answered (3-6).
2) List named entities (people, orgs, products, datasets, standards) to target.
3) Identify related synonyms/aliases/acronyms that should appear in some queries.

Output (no extra text):
SUBQUESTIONS:
- ...
- ...
ENTITIES:
- ...
ALIASES:
- ...
"""

# HyDE: create a hypothetical short answer to mine terms/entities
HYDE_PROMPT = """User topic:
{topic}

Write a concise (120-200 words) hypothetical answer that might be true.
Focus on concrete facts, names, and terms likely to appear in sources.
Do NOT disclaim; just produce the hypothetical answer."""

# Turn structure into actual queries
QUERIES_FROM_STRUCTURE = """Given:
Topic: {topic}

Sub-questions:
{bullets_subquestions}

Entities:
{bullets_entities}

Aliases:
{bullets_aliases}

Create 8 distinct web search queries that together maximize recall and precision.
Guidelines:
- Target key entities, add synonyms in some variants.
- Include operator tricks where helpful: site:, filetype:pdf, intitle:, "quoted phrases".
- Tailor 2 queries to find recent developments (last 1-2 years).
- Tailor 2 queries to find in-depth docs/papers (pdf or arXiv).
- Avoid duplicates; each query must be standalone.

Output:
(one query per line, no numbering)"""

# Lightweight optimization pass: add domains/years
OPTIMIZE_QUERIES_PROMPT = """You are optimizing web search queries.

Context:
- Authority domains to prefer: {authority_domains}
- Recent years to bias toward: {recency_markers}
- Optional domain filters from caller: {domain_filters}

Input queries (one per line):
{queries}

Improve them by:
- For AI/ML/tech queries, add site filters from authority_domains to some variants.
- Add year terms from recency_markers for freshness in some variants.
- Respect domain_filters strictly if provided (only add those).
- Keep queries readable and not overly long.
- Preserve diversity. Return same count.

Output:
(one query per line, no numbering)
"""

