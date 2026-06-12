"""Deep Research — agentic multi-step web research + visual reports.

Ported from Odysseus's IterResearch-style DeepResearcher, rewired to Harvis's
own web search, page extraction, and Ollama LLM bridge. Exposes /api/research/*.
"""

from .router import router  # noqa: F401
