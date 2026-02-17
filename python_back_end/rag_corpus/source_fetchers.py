"""
Source Fetchers for RAG Corpus

Fetchers for different content sources:
- Next.js Documentation
- Stack Overflow Q&A
- GitHub Repositories
"""

import asyncio
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class RawDocument:
    """Raw document fetched from a source."""

    id: str
    url: str
    title: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)


class BaseFetcher(ABC):
    """Base class for content fetchers."""

    SOURCE_NAME: str = "unknown"
    RATE_LIMIT_DELAY: float = 0.5  # seconds between requests

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": "Harvis-RAG-Bot/1.0 (https://github.com/harvis)"
                },
            )
        return self._session

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @abstractmethod
    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """
        Fetch documents from the source.

        Args:
            keywords: Keywords to filter/search content
            extra_urls: Specific URLs to fetch

        Returns:
            List of raw documents
        """
        pass

    def _generate_doc_id(self, url: str, content: str) -> str:
        """Generate unique document ID from URL and content."""
        hash_input = f"{url}:{content[:500]}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


class NextJSDocsFetcher(BaseFetcher):
    """Fetcher for Next.js documentation."""

    SOURCE_NAME = "nextjs_docs"
    BASE_URL = "https://nextjs.org/docs"
    RATE_LIMIT_DELAY = 0.5

    # Key documentation sections to crawl
    DOC_SECTIONS = [
        "/docs/app",
        "/docs/pages",
        "/docs/getting-started",
        "/docs/api-reference",
    ]

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch Next.js documentation."""
        documents = []
        session = await self._get_session()

        # Collect URLs to fetch
        urls_to_fetch = set(extra_urls)

        # If keywords provided, search for relevant pages
        if keywords:
            logger.info(f"Searching Next.js docs for keywords: {keywords}")
            # For now, fetch main sections and filter by keywords
            for section in self.DOC_SECTIONS:
                urls_to_fetch.add(f"https://nextjs.org{section}")
        else:
            # Fetch main documentation index
            urls_to_fetch.add(self.BASE_URL)

        # Fetch sitemap to get all doc URLs
        try:
            sitemap_urls = await self._fetch_sitemap(session)
            if keywords:
                # Filter URLs by keywords
                for url in sitemap_urls:
                    for keyword in keywords:
                        if keyword.lower() in url.lower():
                            urls_to_fetch.add(url)
            else:
                # Limit to first 50 pages if no keywords
                urls_to_fetch.update(list(sitemap_urls)[:50])
        except Exception as e:
            logger.warning(f"Could not fetch sitemap: {e}")

        logger.info(f"Fetching {len(urls_to_fetch)} Next.js doc pages")

        # Fetch each page
        for url in urls_to_fetch:
            try:
                doc = await self._fetch_page(session, url)
                if doc:
                    # If keywords provided, prioritize matching docs but still include others
                    if keywords:
                        content_lower = doc.content.lower()
                        # Check if any keyword matches
                        matches = any(kw.lower() in content_lower for kw in keywords)
                        if matches:
                            logger.debug(f"Page matches keywords: {url}")
                        # Include all fetched docs, keywords just influence URL selection
                        documents.append(doc)
                    else:
                        documents.append(doc)
                else:
                    logger.warning(f"Could not extract content from: {url}")

                await asyncio.sleep(self.RATE_LIMIT_DELAY)

            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")

        logger.info(f"Fetched {len(documents)} Next.js documents")
        return documents

    async def _fetch_sitemap(self, session: aiohttp.ClientSession) -> set:
        """Fetch URLs from Next.js sitemap."""
        urls = set()
        sitemap_url = "https://nextjs.org/sitemap.xml"

        try:
            async with session.get(sitemap_url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Parse sitemap XML
                    soup = BeautifulSoup(text, "lxml-xml")
                    for loc in soup.find_all("loc"):
                        url = loc.text.strip()
                        if "/docs" in url:
                            urls.add(url)
        except Exception as e:
            logger.warning(f"Sitemap fetch failed: {e}")

        return urls

    async def _fetch_page(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[RawDocument]:
        """Fetch and parse a single documentation page."""
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Non-200 status for {url}: {resp.status}")
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title_tag = soup.find("h1")
                title = (
                    title_tag.get_text(strip=True)
                    if title_tag
                    else "Next.js Documentation"
                )

                # Extract main content - try multiple selectors
                main_content = None
                selectors = [
                    ("article", {}),
                    ("main", {}),
                    ("div", {"class": re.compile(r"docs|content|article|prose")}),
                    ("div", {"role": "main"}),
                    ("div", {"id": re.compile(r"content|docs|main")}),
                ]

                for tag, attrs in selectors:
                    main_content = soup.find(tag, attrs) if attrs else soup.find(tag)
                    if main_content:
                        break

                # Last resort: use body
                if not main_content:
                    main_content = soup.find("body")
                    if main_content:
                        logger.debug(f"Using body as fallback for: {url}")

                if not main_content:
                    logger.warning(f"No content found for: {url}")
                    return None

                # Clean content - remove scripts, nav, etc.
                for tag in main_content.find_all(
                    ["script", "style", "nav", "footer", "aside", "header"]
                ):
                    tag.decompose()

                # Get text content with basic formatting
                content = self._extract_text_with_structure(main_content)

                if len(content) < 100:  # Skip very short pages
                    logger.debug(f"Content too short ({len(content)} chars) for: {url}")
                    return None

                logger.debug(f"Extracted {len(content)} chars from: {url}")

                return RawDocument(
                    id=self._generate_doc_id(url, content),
                    url=url,
                    title=title,
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "section": self._get_section(url),
                        "url_path": urlparse(url).path,
                    },
                )

        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None

    def _extract_text_with_structure(self, element) -> str:
        """Extract text while preserving some structure."""
        lines = []

        for child in element.descendants:
            if child.name in ["h1", "h2", "h3", "h4"]:
                text = child.get_text(strip=True)
                if text:
                    marker = "#" * int(child.name[1])
                    lines.append(f"\n{marker} {text}\n")
            elif child.name == "p":
                text = child.get_text(strip=True)
                if text:
                    lines.append(text + "\n")
            elif child.name == "code":
                text = child.get_text(strip=True)
                if text and child.parent.name != "pre":
                    lines.append(f"`{text}`")
            elif child.name == "pre":
                code = child.get_text()
                if code:
                    lines.append(f"\n```\n{code}\n```\n")
            elif child.name == "li":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"• {text}\n")

        return "".join(lines)

    def _get_section(self, url: str) -> str:
        """Extract section from URL."""
        path = urlparse(url).path
        parts = path.split("/")
        if len(parts) >= 3:
            return parts[2]  # e.g., "app", "pages", "getting-started"
        return "general"


class StackOverflowFetcher(BaseFetcher):
    """Fetcher for Stack Overflow Q&A."""

    SOURCE_NAME = "stack_overflow"
    API_BASE = "https://api.stackexchange.com/2.3"
    RATE_LIMIT_DELAY = 1.0  # Stack Exchange has strict rate limits

    DEFAULT_TAGS = ["next.js", "react", "javascript", "typescript"]

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch Stack Overflow questions and answers."""
        documents = []
        session = await self._get_session()

        # Build search query
        tags = keywords if keywords else self.DEFAULT_TAGS

        logger.info(f"Searching Stack Overflow for tags: {tags}")

        # Fetch questions for each tag
        for tag in tags[:5]:  # Limit tags to avoid rate limits
            try:
                questions = await self._search_questions(session, tag)

                for q in questions:
                    doc = await self._fetch_question_with_answers(session, q)
                    if doc:
                        documents.append(doc)
                    await asyncio.sleep(self.RATE_LIMIT_DELAY)

            except Exception as e:
                logger.error(f"Error fetching SO questions for {tag}: {e}")

        # Also fetch any specific URLs provided
        for url in extra_urls:
            if "stackoverflow.com/questions" in url:
                try:
                    q_id = self._extract_question_id(url)
                    if q_id:
                        doc = await self._fetch_question_by_id(session, q_id)
                        if doc:
                            documents.append(doc)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")

        logger.info(f"Fetched {len(documents)} Stack Overflow documents")
        return documents

    async def _search_questions(
        self, session: aiohttp.ClientSession, tag: str, page_size: int = 20
    ) -> List[Dict]:
        """Search for questions by tag."""
        params = {
            "order": "desc",
            "sort": "votes",
            "tagged": tag,
            "site": "stackoverflow",
            "filter": "withbody",
            "pagesize": page_size,
        }

        async with session.get(f"{self.API_BASE}/questions", params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("items", [])
            else:
                logger.warning(f"SO API returned {resp.status}")
                return []

    async def _fetch_question_with_answers(
        self, session: aiohttp.ClientSession, question: Dict
    ) -> Optional[RawDocument]:
        """Fetch question with its answers."""
        q_id = question.get("question_id")
        if not q_id:
            return None

        # Get answers
        params = {
            "order": "desc",
            "sort": "votes",
            "site": "stackoverflow",
            "filter": "withbody",
        }

        answers = []
        try:
            async with session.get(
                f"{self.API_BASE}/questions/{q_id}/answers", params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answers = data.get("items", [])
        except Exception as e:
            logger.warning(f"Could not fetch answers for {q_id}: {e}")

        # Build document content
        title = question.get("title", "Stack Overflow Question")
        q_body = self._clean_html(question.get("body", ""))

        content_parts = [
            f"# {title}\n",
            f"## Question\n{q_body}\n",
        ]

        # Add top answers
        for i, answer in enumerate(answers[:3]):  # Top 3 answers
            a_body = self._clean_html(answer.get("body", ""))
            score = answer.get("score", 0)
            is_accepted = answer.get("is_accepted", False)

            marker = "✓ Accepted Answer" if is_accepted else f"Answer (Score: {score})"
            content_parts.append(f"\n## {marker}\n{a_body}\n")

        content = "\n".join(content_parts)
        url = question.get("link", f"https://stackoverflow.com/questions/{q_id}")

        return RawDocument(
            id=self._generate_doc_id(url, content),
            url=url,
            title=title,
            content=content,
            source=self.SOURCE_NAME,
            metadata={
                "question_id": q_id,
                "score": question.get("score", 0),
                "answer_count": len(answers),
                "tags": question.get("tags", []),
                "is_answered": question.get("is_answered", False),
            },
        )

    async def _fetch_question_by_id(
        self, session: aiohttp.ClientSession, question_id: int
    ) -> Optional[RawDocument]:
        """Fetch a specific question by ID."""
        params = {"site": "stackoverflow", "filter": "withbody"}

        async with session.get(
            f"{self.API_BASE}/questions/{question_id}", params=params
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("items", [])
                if items:
                    return await self._fetch_question_with_answers(session, items[0])
        return None

    def _clean_html(self, html: str) -> str:
        """Clean HTML to plain text."""
        soup = BeautifulSoup(html, "html.parser")

        # Handle code blocks
        for code in soup.find_all("code"):
            code.replace_with(f"`{code.get_text()}`")
        for pre in soup.find_all("pre"):
            pre.replace_with(f"\n```\n{pre.get_text()}\n```\n")

        return soup.get_text(separator="\n").strip()

    def _extract_question_id(self, url: str) -> Optional[int]:
        """Extract question ID from SO URL."""
        match = re.search(r"/questions/(\d+)", url)
        return int(match.group(1)) if match else None


class GitHubFetcher(BaseFetcher):
    """Fetcher for GitHub repositories."""

    SOURCE_NAME = "github"
    API_BASE = "https://api.github.com"
    RATE_LIMIT_DELAY = 0.5

    # Default repos to check for Next.js examples
    DEFAULT_REPOS = [
        "vercel/next.js",
    ]

    # File patterns to include
    INCLUDE_PATTERNS = [
        r"\.md$",
        r"\.mdx$",
        r"\.tsx?$",
        r"\.jsx?$",
    ]

    # Paths to exclude
    EXCLUDE_PATHS = [
        "node_modules",
        ".next",
        "dist",
        "build",
        ".git",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
    ]

    def __init__(self, github_token: Optional[str] = None):
        super().__init__()
        self.github_token = github_token

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get session with GitHub auth headers."""
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Harvis-RAG-Bot/1.0",
                "Accept": "application/vnd.github.v3+json",
            }
            if self.github_token:
                headers["Authorization"] = f"token {self.github_token}"

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30), headers=headers
            )
        return self._session

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch content from GitHub repositories."""
        documents = []
        session = await self._get_session()

        repos_to_fetch = set()

        # Parse extra URLs for repos
        for url in extra_urls:
            if "github.com" in url:
                repo = self._parse_github_url(url)
                if repo:
                    repos_to_fetch.add(repo)

        # Use default repos if none specified
        if not repos_to_fetch and not keywords:
            repos_to_fetch.update(self.DEFAULT_REPOS)

        # Search for repos if keywords provided
        if keywords:
            search_repos = await self._search_repos(session, keywords)
            repos_to_fetch.update(search_repos[:5])  # Limit results

        logger.info(f"Fetching from GitHub repos: {repos_to_fetch}")

        for repo in repos_to_fetch:
            try:
                repo_docs = await self._fetch_repo_contents(session, repo, keywords)
                documents.extend(repo_docs)
            except Exception as e:
                logger.error(f"Error fetching repo {repo}: {e}")

        logger.info(f"Fetched {len(documents)} GitHub documents")
        return documents

    async def _search_repos(
        self, session: aiohttp.ClientSession, keywords: List[str]
    ) -> List[str]:
        """Search for repositories by keywords."""
        query = " ".join(keywords) + " language:typescript language:javascript"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": 10}

        repos = []
        try:
            async with session.get(
                f"{self.API_BASE}/search/repositories", params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("items", []):
                        repos.append(item["full_name"])
        except Exception as e:
            logger.warning(f"GitHub search failed: {e}")

        return repos

    async def _fetch_repo_contents(
        self,
        session: aiohttp.ClientSession,
        repo: str,
        keywords: List[str],
        path: str = "",
    ) -> List[RawDocument]:
        """Fetch relevant files from a repository."""
        documents = []

        # Get repo contents at path
        url = f"{self.API_BASE}/repos/{repo}/contents/{path}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return documents

                items = await resp.json()

                if not isinstance(items, list):
                    items = [items]

                for item in items:
                    item_path = item.get("path", "")
                    item_type = item.get("type")

                    # Skip excluded paths
                    if any(excl in item_path for excl in self.EXCLUDE_PATHS):
                        continue

                    if item_type == "dir":
                        # Recurse into directories (limit depth)
                        if item_path.count("/") < 3:
                            sub_docs = await self._fetch_repo_contents(
                                session, repo, keywords, item_path
                            )
                            documents.extend(sub_docs)
                            await asyncio.sleep(0.2)

                    elif item_type == "file":
                        # Check if file matches patterns
                        if self._should_fetch_file(item_path):
                            doc = await self._fetch_file_content(
                                session, repo, item, keywords
                            )
                            if doc:
                                documents.append(doc)
                            await asyncio.sleep(0.2)

        except Exception as e:
            logger.error(f"Error fetching {repo}/{path}: {e}")

        return documents

    async def _fetch_file_content(
        self, session: aiohttp.ClientSession, repo: str, item: Dict, keywords: List[str]
    ) -> Optional[RawDocument]:
        """Fetch content of a single file."""
        download_url = item.get("download_url")
        if not download_url:
            return None

        try:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    return None

                content = await resp.text()

                # Filter by keywords if provided
                if keywords:
                    content_lower = content.lower()
                    if not any(kw.lower() in content_lower for kw in keywords):
                        return None

                # Skip very large files
                if len(content) > 100000:  # 100KB
                    return None

                file_path = item.get("path", "")
                html_url = item.get("html_url", download_url)

                return RawDocument(
                    id=self._generate_doc_id(html_url, content),
                    url=html_url,
                    title=f"{repo}: {file_path}",
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "repo": repo,
                        "path": file_path,
                        "file_type": file_path.split(".")[-1]
                        if "." in file_path
                        else "unknown",
                        "size": item.get("size", 0),
                    },
                )

        except Exception as e:
            logger.error(f"Error fetching file content: {e}")
            return None

    def _should_fetch_file(self, path: str) -> bool:
        """Check if file should be fetched based on patterns."""
        return any(re.search(pattern, path) for pattern in self.INCLUDE_PATTERNS)

    def _parse_github_url(self, url: str) -> Optional[str]:
        """Parse GitHub URL to extract repo name."""
        match = re.search(r"github\.com/([^/]+/[^/]+)", url)
        return match.group(1) if match else None


class PythonDocsFetcher(BaseFetcher):
    """Fetcher for Python library documentation."""

    SOURCE_NAME = "python_docs"
    RATE_LIMIT_DELAY = 0.5

    # Common documentation hosts
    DOCS_HOSTS = [
        "readthedocs.io",
        "rtfd.io",
        "docs.python.org",
    ]

    # Popular libraries with known doc URLs
    KNOWN_DOCS = {
        "requests": "https://requests.readthedocs.io/en/stable/",
        "pandas": "https://pandas.pydata.org/docs/",
        "numpy": "https://numpy.org/doc/stable/",
        "fastapi": "https://fastapi.tiangolo.com/",
        "flask": "https://flask.palletsprojects.com/en/stable/",
        "django": "https://docs.djangoproject.com/en/stable/",
        "sqlalchemy": "https://docs.sqlalchemy.org/en/stable/",
        "pytest": "https://docs.pytest.org/en/stable/",
        "pydantic": "https://docs.pydantic.dev/latest/",
        "aiohttp": "https://docs.aiohttp.org/en/stable/",
        "httpx": "https://www.python-httpx.org/",
        "rich": "https://rich.readthedocs.io/en/stable/",
        "typer": "https://typer.tiangolo.com/",
        "click": "https://click.palletsprojects.com/en/stable/",
        "beautifulsoup4": "https://beautiful-soup-4.readthedocs.io/en/latest/",
        "scrapy": "https://docs.scrapy.org/en/latest/",
        "celery": "https://docs.celeryq.dev/en/stable/",
        "redis": "https://redis-py.readthedocs.io/en/stable/",
        "psycopg2": "https://www.psycopg.org/docs/",
        "asyncpg": "https://magicstack.github.io/asyncpg/current/",
        "boto3": "https://boto3.amazonaws.com/v1/documentation/api/latest/index.html",
        "tensorflow": "https://www.tensorflow.org/api_docs/python/",
        "pytorch": "https://pytorch.org/docs/stable/",
        "scikit-learn": "https://scikit-learn.org/stable/documentation.html",
        "matplotlib": "https://matplotlib.org/stable/contents.html",
        "opencv-python": "https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html",
        "pillow": "https://pillow.readthedocs.io/en/stable/",
        "langchain": "https://python.langchain.com/docs/",
    }

    def __init__(self, python_libraries: Optional[List[str]] = None):
        super().__init__()
        self.python_libraries = python_libraries or []

    async def fetch(
        self,
        keywords: List[str],
        extra_urls: List[str],
        python_libraries: Optional[List[str]] = None,
    ) -> List[RawDocument]:
        """Fetch Python library documentation."""
        documents = []
        session = await self._get_session()

        # Use provided libraries or from initialization
        libraries = python_libraries or self.python_libraries or keywords

        if not libraries and not extra_urls:
            logger.warning("No Python libraries specified for documentation fetch")
            return documents

        logger.info(f"Fetching Python docs for libraries: {libraries}")

        # Fetch documentation for each library
        for lib in libraries:
            lib_lower = lib.lower().strip()
            try:
                lib_docs = await self._fetch_library_docs(session, lib_lower)
                documents.extend(lib_docs)
            except Exception as e:
                logger.error(f"Error fetching docs for {lib}: {e}")

        # Also fetch specific URLs
        for url in extra_urls:
            if any(
                host in url
                for host in self.DOCS_HOSTS
                + ["python.org", "palletsprojects.com", "pydata.org"]
            ):
                try:
                    doc = await self._fetch_doc_page(session, url, "custom")
                    if doc:
                        documents.append(doc)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")

        logger.info(f"Fetched {len(documents)} Python documentation pages")
        return documents

    async def _fetch_library_docs(
        self, session: aiohttp.ClientSession, library: str
    ) -> List[RawDocument]:
        """Fetch documentation for a specific library."""
        documents = []

        # Check for known documentation URL
        docs_url = self.KNOWN_DOCS.get(library)

        if not docs_url:
            # Try to find docs via ReadTheDocs
            docs_url = await self._find_readthedocs_url(session, library)

        if not docs_url:
            # Try PyPI for project URL
            docs_url = await self._find_pypi_docs_url(session, library)

        if not docs_url:
            logger.warning(f"Could not find documentation URL for {library}")
            return documents

        logger.info(f"Found docs for {library}: {docs_url}")

        # Fetch main page
        main_doc = await self._fetch_doc_page(session, docs_url, library)
        if main_doc:
            documents.append(main_doc)

        # Try to find and fetch linked documentation pages
        linked_pages = await self._find_doc_links(session, docs_url, library)

        for page_url in list(linked_pages)[:30]:  # Limit pages per library
            try:
                doc = await self._fetch_doc_page(session, page_url, library)
                if doc:
                    documents.append(doc)
                await asyncio.sleep(self.RATE_LIMIT_DELAY)
            except Exception as e:
                logger.error(f"Error fetching {page_url}: {e}")

        return documents

    async def _find_readthedocs_url(
        self, session: aiohttp.ClientSession, library: str
    ) -> Optional[str]:
        """Try to find ReadTheDocs URL for a library."""
        # Common RTD URL patterns
        patterns = [
            f"https://{library}.readthedocs.io/en/stable/",
            f"https://{library}.readthedocs.io/en/latest/",
            f"https://{library.replace('-', '')}.readthedocs.io/en/stable/",
        ]

        for url in patterns:
            try:
                async with session.head(url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        return str(resp.url)
            except:
                pass

        return None

    async def _find_pypi_docs_url(
        self, session: aiohttp.ClientSession, library: str
    ) -> Optional[str]:
        """Find documentation URL from PyPI package info."""
        pypi_url = f"https://pypi.org/pypi/{library}/json"

        try:
            async with session.get(pypi_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    info = data.get("info", {})

                    # Check project_urls for documentation
                    project_urls = info.get("project_urls") or {}
                    for key, url in project_urls.items():
                        key_lower = key.lower()
                        if any(
                            k in key_lower
                            for k in ["doc", "document", "guide", "reference"]
                        ):
                            return url

                    # Fall back to home page or project URL
                    for key in ["home_page", "project_url"]:
                        url = info.get(key)
                        if url and "github.com" not in url:
                            return url
        except Exception as e:
            logger.warning(f"PyPI lookup failed for {library}: {e}")

        return None

    async def _find_doc_links(
        self, session: aiohttp.ClientSession, base_url: str, library: str
    ) -> set:
        """Find documentation page links from base URL."""
        links = set()

        try:
            async with session.get(base_url) as resp:
                if resp.status != 200:
                    return links

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Find relevant links
                base_domain = urlparse(base_url).netloc

                for a in soup.find_all("a", href=True):
                    href = a["href"]

                    # Make absolute URL
                    if href.startswith("/"):
                        href = urljoin(base_url, href)
                    elif not href.startswith("http"):
                        href = urljoin(base_url, href)

                    # Only include links to same domain
                    if urlparse(href).netloc == base_domain:
                        # Skip anchors and common non-doc paths
                        if "#" not in href and not any(
                            skip in href
                            for skip in [
                                "/search",
                                "/genindex",
                                "/py-modindex",
                                "/_",
                                "/edit/",
                                ".zip",
                                ".tar",
                                ".pdf",
                                ".png",
                                ".jpg",
                                ".svg",
                            ]
                        ):
                            links.add(href)

        except Exception as e:
            logger.warning(f"Could not find doc links: {e}")

        return links

    async def _fetch_doc_page(
        self, session: aiohttp.ClientSession, url: str, library: str
    ) -> Optional[RawDocument]:
        """Fetch and parse a documentation page."""
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title_tag = soup.find("h1") or soup.find("title")
                title = (
                    title_tag.get_text(strip=True)
                    if title_tag
                    else f"{library} Documentation"
                )

                # Extract main content
                main = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find("div", {"role": "main"})
                    or soup.find("div", class_=re.compile(r"document|content|body"))
                )

                if not main:
                    main = soup.find("body")

                if not main:
                    return None

                # Remove unwanted elements
                for tag in main.find_all(
                    ["script", "style", "nav", "aside", "footer", "header"]
                ):
                    tag.decompose()

                # Extract structured text
                content = self._extract_doc_content(main)

                if len(content) < 100:
                    return None

                return RawDocument(
                    id=self._generate_doc_id(url, content),
                    url=url,
                    title=title,
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "library": library,
                        "url_path": urlparse(url).path,
                    },
                )

        except Exception as e:
            logger.error(f"Error fetching doc page {url}: {e}")
            return None

    def _extract_doc_content(self, element) -> str:
        """Extract text content preserving structure."""
        lines = []

        for child in element.descendants:
            if hasattr(child, "name"):
                if child.name in ["h1", "h2", "h3", "h4", "h5"]:
                    text = child.get_text(strip=True)
                    if text:
                        level = int(child.name[1])
                        lines.append(f"\n{'#' * level} {text}\n")
                elif child.name == "p":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(text + "\n")
                elif child.name == "li":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"• {text}\n")
                elif child.name == "pre":
                    code = child.get_text()
                    if code:
                        lines.append(f"\n```\n{code}\n```\n")
                elif child.name == "code" and child.parent.name != "pre":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"`{text}`")

        return "".join(lines)


class LocalDocsFetcher(BaseFetcher):
    """Fetcher for local documentation files (markdown)."""

    SOURCE_NAME = "local_docs"

    # Default directories to scan for documentation
    DEFAULT_DOCS_DIRS = [
        "/app/docs",  # Container path
        "/workspaces/aidev/docs",  # Dev container
        "./docs",  # Relative to cwd
    ]

    # File patterns to include
    INCLUDE_PATTERNS = [
        r"\.md$",
        r"\.mdx$",
        r"\.txt$",
    ]

    # Files/directories to exclude
    EXCLUDE_PATTERNS = [
        r"node_modules",
        r"\.git",
        r"__pycache__",
        r"\.pyc$",
        r"\.env",
    ]

    def __init__(self, docs_dirs: Optional[List[str]] = None):
        super().__init__()
        self.docs_dirs = docs_dirs or self.DEFAULT_DOCS_DIRS

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch local documentation files."""
        import os
        import glob

        documents = []

        # Find valid docs directories
        valid_dirs = []
        for docs_dir in self.docs_dirs:
            expanded = os.path.expanduser(docs_dir)
            if os.path.isdir(expanded):
                valid_dirs.append(expanded)

        # Also check extra_urls for local paths
        for path in extra_urls:
            if os.path.isdir(path):
                valid_dirs.append(path)
            elif os.path.isfile(path):
                doc = self._read_file(path)
                if doc:
                    documents.append(doc)

        if not valid_dirs:
            logger.warning(
                f"No valid docs directories found. Checked: {self.docs_dirs}"
            )
            return documents

        logger.info(f"Scanning local docs directories: {valid_dirs}")

        for docs_dir in valid_dirs:
            # Walk through directory
            for root, dirs, files in os.walk(docs_dir):
                # Filter out excluded directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(
                        re.search(pattern, d) for pattern in self.EXCLUDE_PATTERNS
                    )
                ]

                for filename in files:
                    filepath = os.path.join(root, filename)

                    # Check if file matches include patterns
                    if not any(
                        re.search(pattern, filename)
                        for pattern in self.INCLUDE_PATTERNS
                    ):
                        continue

                    # Check exclude patterns
                    if any(
                        re.search(pattern, filepath)
                        for pattern in self.EXCLUDE_PATTERNS
                    ):
                        continue

                    # Read and parse file
                    doc = self._read_file(filepath, keywords)
                    if doc:
                        documents.append(doc)

        logger.info(f"Fetched {len(documents)} local documentation files")
        return documents

    def _read_file(
        self, filepath: str, keywords: Optional[List[str]] = None
    ) -> Optional[RawDocument]:
        """Read a single documentation file."""
        import os

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Skip empty files
            if len(content.strip()) < 50:
                return None

            # Skip very large files
            if len(content) > 200000:  # 200KB
                logger.warning(f"Skipping large file: {filepath}")
                return None

            # Filter by keywords if provided
            if keywords:
                content_lower = content.lower()
                if not any(kw.lower() in content_lower for kw in keywords):
                    return None

            # Extract title from first heading or filename
            title = os.path.basename(filepath)
            lines = content.split("\n")
            for line in lines[:10]:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            # Create file URL (file:// protocol)
            file_url = f"file://{os.path.abspath(filepath)}"

            # Determine relative path for metadata
            rel_path = filepath
            for docs_dir in self.docs_dirs:
                if filepath.startswith(docs_dir):
                    rel_path = filepath[len(docs_dir) :].lstrip("/")
                    break

            return RawDocument(
                id=self._generate_doc_id(file_url, content),
                url=file_url,
                title=title,
                content=content,
                source=self.SOURCE_NAME,
                metadata={
                    "filepath": filepath,
                    "relative_path": rel_path,
                    "file_type": filepath.split(".")[-1]
                    if "." in filepath
                    else "unknown",
                    "size_bytes": len(content),
                },
            )

        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return None


class DockerDocsFetcher(BaseFetcher):
    """Fetcher for Docker documentation."""

    SOURCE_NAME = "docker_docs"
    BASE_URL = "https://docs.docker.com"
    RATE_LIMIT_DELAY = 0.5

    # Known documentation sections/topics
    KNOWN_TOPICS = {
        "engine": "https://docs.docker.com/engine/",
        "compose": "https://docs.docker.com/compose/",
        "swarm": "https://docs.docker.com/engine/swarm/",
        "registry": "https://docs.docker.com/registry/",
        "hub": "https://docs.docker.com/docker-hub/",
        "buildx": "https://docs.docker.com/build/",
        "cli": "https://docs.docker.com/engine/reference/commandline/",
        "dockerfile": "https://docs.docker.com/engine/reference/builder/",
        "networking": "https://docs.docker.com/network/",
        "storage": "https://docs.docker.com/storage/",
        "security": "https://docs.docker.com/engine/security/",
    }

    def __init__(self, docker_topics: Optional[List[str]] = None):
        super().__init__()
        self.docker_topics = docker_topics or []

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch Docker documentation."""
        documents = []
        session = await self._get_session()

        # 1. If topics specified, fetch those sections
        if self.docker_topics:
            logger.info(f"Fetching Docker docs for topics: {self.docker_topics}")
            for topic in self.docker_topics:
                if topic in self.KNOWN_TOPICS:
                    topic_url = self.KNOWN_TOPICS[topic]
                    try:
                        topic_docs = await self._fetch_section(
                            session, topic_url, topic
                        )
                        documents.extend(topic_docs)
                    except Exception as e:
                        logger.error(f"Error fetching Docker topic {topic}: {e}")
                else:
                    logger.warning(
                        f"Unknown Docker topic: {topic}. Valid topics: {list(self.KNOWN_TOPICS.keys())}"
                    )

        # 2. Fetch custom URLs
        for url in extra_urls:
            if "docs.docker.com" in url or "docker.com" in url:
                try:
                    doc = await self._fetch_doc_page(session, url, "custom")
                    if doc:
                        documents.append(doc)
                except Exception as e:
                    logger.error(f"Error fetching Docker URL {url}: {e}")

        # 3. If no topics/URLs specified, fetch all from sitemap
        if not self.docker_topics and not extra_urls:
            logger.info("Fetching all Docker documentation from sitemap")
            try:
                all_docs = await self._fetch_from_sitemap(session)
                documents.extend(all_docs)
            except Exception as e:
                logger.error(f"Error fetching Docker sitemap: {e}")

        logger.info(f"Fetched {len(documents)} Docker documents")
        return documents

    async def _fetch_section(
        self, session: aiohttp.ClientSession, section_url: str, topic: str
    ) -> List[RawDocument]:
        """Fetch all pages from a documentation section."""
        documents = []

        try:
            # Fetch the section page
            async with session.get(section_url) as resp:
                if resp.status != 200:
                    logger.warning(f"Non-200 status for {section_url}: {resp.status}")
                    return documents

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Find all links within this section
                section_links = set()
                base_domain = urlparse(section_url).netloc

                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # Make absolute URL
                    if href.startswith("/"):
                        href = urljoin(f"https://{base_domain}", href)
                    elif not href.startswith("http"):
                        href = urljoin(section_url, href)

                    # Only include links to same domain and within docs
                    if urlparse(href).netloc == base_domain and "/" in href:
                        # Skip anchors, images, and non-doc paths
                        if "#" not in href and not any(
                            skip in href.lower()
                            for skip in [
                                ".png",
                                ".jpg",
                                ".gif",
                                ".pdf",
                                ".zip",
                                ".tar",
                                "/search",
                                "/genindex",
                                "/_",
                            ]
                        ):
                            section_links.add(href)

                # Limit to first 30 pages per section
                for page_url in list(section_links)[:30]:
                    try:
                        doc = await self._fetch_doc_page(session, page_url, topic)
                        if doc:
                            documents.append(doc)
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    except Exception as e:
                        logger.debug(f"Error fetching {page_url}: {e}")

        except Exception as e:
            logger.error(f"Error fetching section {section_url}: {e}")

        return documents

    async def _fetch_from_sitemap(
        self, session: aiohttp.ClientSession
    ) -> List[RawDocument]:
        """Fetch all documentation pages from sitemap."""
        documents = []

        try:
            sitemap_url = "https://docs.docker.com/sitemap.xml"
            async with session.get(sitemap_url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    soup = BeautifulSoup(text, "lxml-xml")

                    urls = []
                    for loc in soup.find_all("loc"):
                        url = loc.text.strip()
                        # Filter to only documentation pages
                        if "/" in url and not any(
                            skip in url for skip in [".png", ".jpg", ".gif", ".pdf"]
                        ):
                            urls.append(url)

                    logger.info(f"Found {len(urls)} URLs in Docker sitemap")

                    # Limit to first 100 pages for performance
                    for url in urls[:100]:
                        try:
                            doc = await self._fetch_doc_page(session, url, "general")
                            if doc:
                                documents.append(doc)
                            await asyncio.sleep(self.RATE_LIMIT_DELAY)
                        except Exception as e:
                            logger.debug(f"Error fetching {url}: {e}")
                else:
                    logger.warning(f"Docker sitemap returned status {resp.status}")
        except Exception as e:
            logger.error(f"Error fetching Docker sitemap: {e}")

        return documents

    async def _fetch_doc_page(
        self, session: aiohttp.ClientSession, url: str, topic: str
    ) -> Optional[RawDocument]:
        """Fetch and parse a single documentation page."""
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title_tag = soup.find("h1") or soup.find("title")
                title = (
                    title_tag.get_text(strip=True)
                    if title_tag
                    else "Docker Documentation"
                )

                # Extract main content
                main = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find("div", {"role": "main"})
                    or soup.find("div", class_=re.compile(r"content|body|article"))
                )

                if not main:
                    main = soup.find("body")

                if not main:
                    return None

                # Remove unwanted elements
                for tag in main.find_all(
                    ["script", "style", "nav", "aside", "footer", "header"]
                ):
                    tag.decompose()

                # Extract structured text
                content = self._extract_doc_content(main)

                if len(content) < 100:
                    return None

                return RawDocument(
                    id=self._generate_doc_id(url, content),
                    url=url,
                    title=title,
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "topic": topic,
                        "url_path": urlparse(url).path,
                    },
                )

        except Exception as e:
            logger.error(f"Error fetching Docker doc page {url}: {e}")
            return None

    def _extract_doc_content(self, element) -> str:
        """Extract text content preserving structure."""
        lines = []

        for child in element.descendants:
            if hasattr(child, "name"):
                if child.name in ["h1", "h2", "h3", "h4", "h5"]:
                    text = child.get_text(strip=True)
                    if text:
                        level = int(child.name[1])
                        lines.append(f"\n{'#' * level} {text}\n")
                elif child.name == "p":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(text + "\n")
                elif child.name == "li":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"• {text}\n")
                elif child.name == "pre":
                    code = child.get_text()
                    if code:
                        lines.append(f"\n```\n{code}\n```\n")
                elif child.name == "code" and child.parent.name != "pre":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"`{text}`")

        return "".join(lines)


class KubernetesDocsFetcher(BaseFetcher):
    """Fetcher for Kubernetes documentation."""

    SOURCE_NAME = "kubernetes_docs"
    BASE_URL = "https://kubernetes.io/docs"
    RATE_LIMIT_DELAY = 0.5

    # Known documentation sections/topics
    KNOWN_TOPICS = {
        "concepts": "https://kubernetes.io/docs/concepts/",
        "tasks": "https://kubernetes.io/docs/tasks/",
        "reference": "https://kubernetes.io/docs/reference/",
        "tutorials": "https://kubernetes.io/docs/tutorials/",
        "setup": "https://kubernetes.io/docs/setup/",
        "networking": "https://kubernetes.io/docs/concepts/services-networking/",
        "storage": "https://kubernetes.io/docs/concepts/storage/",
        "security": "https://kubernetes.io/docs/concepts/security/",
        "scheduling": "https://kubernetes.io/docs/concepts/scheduling-eviction/",
        "workloads": "https://kubernetes.io/docs/concepts/workloads/",
    }

    def __init__(self, kubernetes_topics: Optional[List[str]] = None):
        super().__init__()
        self.kubernetes_topics = kubernetes_topics or []

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch Kubernetes documentation."""
        documents = []
        session = await self._get_session()

        # 1. If topics specified, fetch those sections
        if self.kubernetes_topics:
            logger.info(
                f"Fetching Kubernetes docs for topics: {self.kubernetes_topics}"
            )
            for topic in self.kubernetes_topics:
                if topic in self.KNOWN_TOPICS:
                    topic_url = self.KNOWN_TOPICS[topic]
                    try:
                        topic_docs = await self._fetch_section(
                            session, topic_url, topic
                        )
                        documents.extend(topic_docs)
                    except Exception as e:
                        logger.error(f"Error fetching Kubernetes topic {topic}: {e}")
                else:
                    logger.warning(
                        f"Unknown Kubernetes topic: {topic}. Valid topics: {list(self.KNOWN_TOPICS.keys())}"
                    )

        # 2. Fetch custom URLs
        for url in extra_urls:
            if "kubernetes.io" in url or "k8s.io" in url:
                try:
                    doc = await self._fetch_doc_page(session, url, "custom")
                    if doc:
                        documents.append(doc)
                except Exception as e:
                    logger.error(f"Error fetching Kubernetes URL {url}: {e}")

        # 3. If no topics/URLs specified, fetch all from sitemap
        if not self.kubernetes_topics and not extra_urls:
            logger.info("Fetching all Kubernetes documentation from sitemap")
            try:
                all_docs = await self._fetch_from_sitemap(session)
                documents.extend(all_docs)
            except Exception as e:
                logger.error(f"Error fetching Kubernetes sitemap: {e}")

        logger.info(f"Fetched {len(documents)} Kubernetes documents")
        return documents

    async def _fetch_section(
        self, session: aiohttp.ClientSession, section_url: str, topic: str
    ) -> List[RawDocument]:
        """Fetch all pages from a documentation section."""
        documents = []

        try:
            # Fetch the section page
            async with session.get(section_url) as resp:
                if resp.status != 200:
                    logger.warning(f"Non-200 status for {section_url}: {resp.status}")
                    return documents

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Find all links within this section
                section_links = set()
                base_domain = urlparse(section_url).netloc

                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # Make absolute URL
                    if href.startswith("/"):
                        href = urljoin(f"https://{base_domain}", href)
                    elif not href.startswith("http"):
                        href = urljoin(section_url, href)

                    # Only include links to same domain and within docs
                    if urlparse(href).netloc == base_domain and "/docs/" in href:
                        # Skip anchors, images, and non-doc paths
                        if "#" not in href and not any(
                            skip in href.lower()
                            for skip in [
                                ".png",
                                ".jpg",
                                ".gif",
                                ".pdf",
                                ".zip",
                                ".tar",
                                "/search",
                                "/genindex",
                                "/_",
                            ]
                        ):
                            section_links.add(href)

                # Limit to first 30 pages per section
                for page_url in list(section_links)[:30]:
                    try:
                        doc = await self._fetch_doc_page(session, page_url, topic)
                        if doc:
                            documents.append(doc)
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    except Exception as e:
                        logger.debug(f"Error fetching {page_url}: {e}")

        except Exception as e:
            logger.error(f"Error fetching section {section_url}: {e}")

        return documents

    async def _fetch_from_sitemap(
        self, session: aiohttp.ClientSession
    ) -> List[RawDocument]:
        """Fetch all documentation pages from sitemap."""
        documents = []

        try:
            # Kubernetes uses a sitemap index, so we need to fetch the English sitemap directly
            # The main sitemap.xml is a sitemapindex pointing to language-specific sitemaps
            sitemap_url = "https://kubernetes.io/en/sitemap.xml"
            logger.info(f"Fetching Kubernetes English sitemap: {sitemap_url}")

            async with session.get(sitemap_url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    soup = BeautifulSoup(text, "lxml-xml")

                    urls = []

                    # Check if this is a sitemap index (contains <sitemapindex> root)
                    if soup.find("sitemapindex"):
                        logger.info("Found sitemap index, fetching nested sitemaps")
                        # This shouldn't happen for the /en/ sitemap, but handle it anyway
                        for sitemap_loc in soup.find_all("loc"):
                            nested_url = sitemap_loc.text.strip()
                            if "sitemap" in nested_url.lower():
                                nested_urls = await self._parse_sitemap(session, nested_url)
                                urls.extend(nested_urls)
                    else:
                        # Regular sitemap with direct URLs
                        for loc in soup.find_all("loc"):
                            url = loc.text.strip()
                            # Filter to only documentation pages
                            if "/docs/" in url and not any(
                                skip in url for skip in [".png", ".jpg", ".gif", ".pdf"]
                            ):
                                urls.append(url)

                    logger.info(f"Found {len(urls)} URLs in Kubernetes sitemap")

                    # Limit to first 100 pages for performance
                    for url in urls[:100]:
                        try:
                            doc = await self._fetch_doc_page(session, url, "general")
                            if doc:
                                documents.append(doc)
                            await asyncio.sleep(self.RATE_LIMIT_DELAY)
                        except Exception as e:
                            logger.debug(f"Error fetching {url}: {e}")
                else:
                    logger.warning(f"Kubernetes sitemap returned status {resp.status}")
        except Exception as e:
            logger.error(f"Error fetching Kubernetes sitemap: {e}")

        return documents

    async def _parse_sitemap(
        self, session: aiohttp.ClientSession, sitemap_url: str
    ) -> List[str]:
        """Parse a sitemap and extract documentation URLs."""
        urls = []
        try:
            async with session.get(sitemap_url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    soup = BeautifulSoup(text, "lxml-xml")
                    for loc in soup.find_all("loc"):
                        url = loc.text.strip()
                        if "/docs/" in url and not any(
                            skip in url for skip in [".png", ".jpg", ".gif", ".pdf"]
                        ):
                            urls.append(url)
        except Exception as e:
            logger.warning(f"Error parsing sitemap {sitemap_url}: {e}")
        return urls

    async def _fetch_doc_page(
        self, session: aiohttp.ClientSession, url: str, topic: str
    ) -> Optional[RawDocument]:
        """Fetch and parse a single documentation page."""
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title_tag = soup.find("h1") or soup.find("title")
                title = (
                    title_tag.get_text(strip=True)
                    if title_tag
                    else "Kubernetes Documentation"
                )

                # Extract main content
                main = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find("div", {"role": "main"})
                    or soup.find("div", class_=re.compile(r"content|body|article"))
                )

                if not main:
                    main = soup.find("body")

                if not main:
                    return None

                # Remove unwanted elements
                for tag in main.find_all(
                    ["script", "style", "nav", "aside", "footer", "header"]
                ):
                    tag.decompose()

                # Extract structured text
                content = self._extract_doc_content(main)

                if len(content) < 100:
                    return None

                return RawDocument(
                    id=self._generate_doc_id(url, content),
                    url=url,
                    title=title,
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "topic": topic,
                        "url_path": urlparse(url).path,
                    },
                )

        except Exception as e:
            logger.error(f"Error fetching Kubernetes doc page {url}: {e}")
            return None

    def _extract_doc_content(self, element) -> str:
        """Extract text content preserving structure."""
        lines = []

        for child in element.descendants:
            if hasattr(child, "name"):
                if child.name in ["h1", "h2", "h3", "h4", "h5"]:
                    text = child.get_text(strip=True)
                    if text:
                        level = int(child.name[1])
                        lines.append(f"\n{'#' * level} {text}\n")
                elif child.name == "p":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(text + "\n")
                elif child.name == "li":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"• {text}\n")
                elif child.name == "pre":
                    code = child.get_text()
                    if code:
                        lines.append(f"\n```\n{code}\n```\n")
                elif child.name == "code" and child.parent.name != "pre":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"`{text}`")

        return "".join(lines)


class GenericDocsFetcher(BaseFetcher):
    """
    Generic fetcher for documentation sites.

    Configurable via SourceConfig to handle various documentation sites
    without requiring custom fetcher code.
    """

    SOURCE_NAME = "generic_docs"
    RATE_LIMIT_DELAY = 0.5

    def __init__(
        self,
        source_id: str = "generic",
        base_url: str = "",
        sitemap_url: Optional[str] = None,
        url_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_pages: int = 100,
        rate_limit_delay: float = 0.5,
    ):
        super().__init__()
        self.source_id = source_id
        self.SOURCE_NAME = source_id
        self.base_url = base_url.rstrip("/")
        self.sitemap_url = sitemap_url
        self.url_patterns = url_patterns or []
        self.exclude_patterns = exclude_patterns or []
        self.max_pages = max_pages
        self.RATE_LIMIT_DELAY = rate_limit_delay

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch documentation from the configured site."""
        documents = []
        session = await self._get_session()

        urls_to_fetch = set(extra_urls)

        # Try to get URLs from sitemap first
        if self.sitemap_url:
            try:
                sitemap_urls = await self._fetch_sitemap(session, self.sitemap_url)
                urls_to_fetch.update(sitemap_urls)
                logger.info(f"Found {len(sitemap_urls)} URLs from sitemap for {self.source_id}")
            except Exception as e:
                logger.warning(f"Could not fetch sitemap for {self.source_id}: {e}")

        # If no sitemap or empty, try crawling from base URL
        if not urls_to_fetch and self.base_url:
            urls_to_fetch.add(self.base_url)
            try:
                crawled = await self._crawl_links(session, self.base_url)
                urls_to_fetch.update(crawled)
            except Exception as e:
                logger.warning(f"Could not crawl {self.base_url}: {e}")

        # Filter URLs by patterns
        urls_to_fetch = self._filter_urls(urls_to_fetch)

        # Limit number of pages
        urls_list = list(urls_to_fetch)[:self.max_pages]
        logger.info(f"Fetching {len(urls_list)} pages for {self.source_id}")

        # Fetch each page
        for url in urls_list:
            try:
                doc = await self._fetch_page(session, url)
                if doc:
                    # Filter by keywords if provided
                    if keywords:
                        content_lower = doc.content.lower()
                        if any(kw.lower() in content_lower for kw in keywords):
                            documents.append(doc)
                    else:
                        documents.append(doc)

                await asyncio.sleep(self.RATE_LIMIT_DELAY)

            except Exception as e:
                logger.debug(f"Error fetching {url}: {e}")

        logger.info(f"Fetched {len(documents)} documents for {self.source_id}")
        return documents

    async def _fetch_sitemap(self, session: aiohttp.ClientSession, sitemap_url: str) -> set:
        """Fetch URLs from sitemap (handles sitemap indexes too)."""
        urls = set()

        try:
            async with session.get(sitemap_url) as resp:
                if resp.status != 200:
                    return urls

                text = await resp.text()
                soup = BeautifulSoup(text, "lxml-xml")

                # Check if this is a sitemap index
                if soup.find("sitemapindex"):
                    # Fetch nested sitemaps
                    for sitemap_loc in soup.find_all("loc"):
                        nested_url = sitemap_loc.text.strip()
                        if "sitemap" in nested_url.lower():
                            nested_urls = await self._fetch_sitemap(session, nested_url)
                            urls.update(nested_urls)
                            if len(urls) >= self.max_pages * 2:
                                break
                else:
                    # Regular sitemap
                    for loc in soup.find_all("loc"):
                        url = loc.text.strip()
                        urls.add(url)

        except Exception as e:
            logger.warning(f"Error parsing sitemap {sitemap_url}: {e}")

        return urls

    async def _crawl_links(self, session: aiohttp.ClientSession, start_url: str, depth: int = 2) -> set:
        """Crawl links from a starting URL."""
        urls = set()
        visited = set()
        to_visit = [(start_url, 0)]
        base_domain = urlparse(start_url).netloc

        while to_visit and len(urls) < self.max_pages * 2:
            current_url, current_depth = to_visit.pop(0)

            if current_url in visited or current_depth > depth:
                continue

            visited.add(current_url)

            try:
                async with session.get(current_url) as resp:
                    if resp.status != 200:
                        continue

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    for a in soup.find_all("a", href=True):
                        href = a["href"]

                        # Make absolute
                        if href.startswith("/"):
                            href = urljoin(f"https://{base_domain}", href)
                        elif not href.startswith("http"):
                            href = urljoin(current_url, href)

                        # Only same domain
                        if urlparse(href).netloc == base_domain:
                            # Skip anchors, files, etc.
                            if "#" not in href and not any(
                                ext in href.lower()
                                for ext in [".png", ".jpg", ".gif", ".pdf", ".zip", ".tar"]
                            ):
                                urls.add(href)
                                if current_depth < depth:
                                    to_visit.append((href, current_depth + 1))

                await asyncio.sleep(0.2)

            except Exception as e:
                logger.debug(f"Error crawling {current_url}: {e}")

        return urls

    def _filter_urls(self, urls: set) -> set:
        """Filter URLs by configured patterns."""
        filtered = set()

        for url in urls:
            # Check include patterns (if specified, URL must match at least one)
            if self.url_patterns:
                if not any(pattern in url for pattern in self.url_patterns):
                    continue

            # Check exclude patterns
            if self.exclude_patterns:
                if any(pattern in url for pattern in self.exclude_patterns):
                    continue

            filtered.add(url)

        return filtered

    async def _fetch_page(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[RawDocument]:
        """Fetch and parse a single documentation page."""
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title_tag = soup.find("h1") or soup.find("title")
                title = (
                    title_tag.get_text(strip=True)
                    if title_tag
                    else "Documentation"
                )

                # Extract main content - try multiple selectors
                main = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find("div", {"role": "main"})
                    or soup.find("div", class_=re.compile(r"content|body|article|docs|prose"))
                    or soup.find("div", id=re.compile(r"content|docs|main"))
                )

                if not main:
                    main = soup.find("body")

                if not main:
                    return None

                # Remove unwanted elements
                for tag in main.find_all(
                    ["script", "style", "nav", "aside", "footer", "header", "noscript"]
                ):
                    tag.decompose()

                # Extract structured text
                content = self._extract_doc_content(main)

                if len(content) < 100:
                    return None

                return RawDocument(
                    id=self._generate_doc_id(url, content),
                    url=url,
                    title=title,
                    content=content,
                    source=self.SOURCE_NAME,
                    metadata={
                        "url_path": urlparse(url).path,
                    },
                )

        except Exception as e:
            logger.debug(f"Error fetching page {url}: {e}")
            return None

    def _extract_doc_content(self, element) -> str:
        """Extract text content preserving structure."""
        lines = []

        for child in element.descendants:
            if hasattr(child, "name"):
                if child.name in ["h1", "h2", "h3", "h4", "h5"]:
                    text = child.get_text(strip=True)
                    if text:
                        level = int(child.name[1])
                        lines.append(f"\n{'#' * level} {text}\n")
                elif child.name == "p":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(text + "\n")
                elif child.name == "li":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"- {text}\n")
                elif child.name == "pre":
                    code = child.get_text()
                    if code:
                        lines.append(f"\n```\n{code}\n```\n")
                elif child.name == "code" and child.parent.name != "pre":
                    text = child.get_text(strip=True)
                    if text:
                        lines.append(f"`{text}`")

        return "".join(lines)


class AnsiblePlaybookFetcher(BaseFetcher):
    """
    Fetcher for Ansible playbooks and roles.

    Handles complex YAML structures with Jinja2 templating,
    role hierarchies, and variable files. Uses qwen3-embedding
    for high-dimensional vectors to capture nuanced relationships.
    """

    SOURCE_NAME = "ansible_playbooks"

    # Default directories to scan for playbooks
    DEFAULT_PLAYBOOK_DIRS = [
        "/app/ansible",
        "/app/playbooks",
        "/workspaces/aidev/ansible",
        "./ansible",
        "./playbooks",
    ]

    # File patterns to include
    INCLUDE_PATTERNS = [
        r"\.ya?ml$",
    ]

    # Files/directories to exclude
    EXCLUDE_PATTERNS = [
        r"node_modules",
        r"\.git",
        r"__pycache__",
        r"\.pyc$",
        r"\.env",
        r"\.venv",
        r"venv/",
        r"\.tox",
        r"molecule/",  # Molecule test configs can be noisy
    ]

    # Ansible-specific file types for metadata
    ANSIBLE_FILE_TYPES = {
        "tasks/main": "tasks",
        "handlers/main": "handlers",
        "vars/main": "variables",
        "defaults/main": "defaults",
        "meta/main": "role_metadata",
        "playbook": "playbook",
        "inventory": "inventory",
        "group_vars": "group_variables",
        "host_vars": "host_variables",
    }

    def __init__(self, playbook_dirs: Optional[List[str]] = None):
        super().__init__()
        self.playbook_dirs = playbook_dirs or self.DEFAULT_PLAYBOOK_DIRS

    async def fetch(
        self, keywords: List[str], extra_urls: List[str]
    ) -> List[RawDocument]:
        """Fetch Ansible playbooks and roles from local directories."""
        import os
        import yaml

        documents = []

        # Find valid playbook directories
        valid_dirs = []
        for playbook_dir in self.playbook_dirs:
            expanded = os.path.expanduser(playbook_dir)
            if os.path.isdir(expanded):
                valid_dirs.append(expanded)

        # Also check extra_urls for local paths
        for path in extra_urls:
            if os.path.isdir(path):
                valid_dirs.append(path)
            elif os.path.isfile(path) and path.endswith(('.yml', '.yaml')):
                doc = self._read_playbook_file(path, keywords)
                if doc:
                    documents.append(doc)

        if not valid_dirs:
            logger.warning(
                f"No valid Ansible directories found. Checked: {self.playbook_dirs}"
            )
            return documents

        logger.info(f"Scanning Ansible playbook directories: {valid_dirs}")

        for playbook_dir in valid_dirs:
            # Walk through directory
            for root, dirs, files in os.walk(playbook_dir):
                # Filter out excluded directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(
                        re.search(pattern, d) for pattern in self.EXCLUDE_PATTERNS
                    )
                ]

                for filename in files:
                    filepath = os.path.join(root, filename)

                    # Check if file matches YAML patterns
                    if not any(
                        re.search(pattern, filename)
                        for pattern in self.INCLUDE_PATTERNS
                    ):
                        continue

                    # Check exclude patterns
                    if any(
                        re.search(pattern, filepath)
                        for pattern in self.EXCLUDE_PATTERNS
                    ):
                        continue

                    # Read and parse playbook file
                    doc = self._read_playbook_file(filepath, keywords)
                    if doc:
                        documents.append(doc)

        logger.info(f"Fetched {len(documents)} Ansible playbook documents")
        return documents

    def _read_playbook_file(
        self, filepath: str, keywords: Optional[List[str]] = None
    ) -> Optional[RawDocument]:
        """Read and parse an Ansible playbook/role file."""
        import os
        import yaml

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                raw_content = f.read()

            # Skip empty files
            if len(raw_content.strip()) < 20:
                return None

            # Skip very large files
            if len(raw_content) > 500000:  # 500KB
                logger.warning(f"Skipping large Ansible file: {filepath}")
                return None

            # Filter by keywords if provided
            if keywords:
                content_lower = raw_content.lower()
                if not any(kw.lower() in content_lower for kw in keywords):
                    return None

            # Parse YAML to extract structure (for metadata)
            parsed_content = None
            try:
                parsed_content = yaml.safe_load(raw_content)
            except yaml.YAMLError:
                # File may have Jinja2 templates that break YAML parsing
                # Still include it as raw content
                pass

            # Determine file type
            file_type = self._detect_ansible_file_type(filepath, parsed_content)

            # Extract title from filename or content
            title = self._extract_title(filepath, parsed_content, file_type)

            # Build enriched content with context
            enriched_content = self._enrich_content(
                filepath, raw_content, parsed_content, file_type
            )

            # Create file URL (file:// protocol)
            file_url = f"file://{os.path.abspath(filepath)}"

            # Determine relative path for metadata
            rel_path = filepath
            for playbook_dir in self.playbook_dirs:
                if filepath.startswith(playbook_dir):
                    rel_path = filepath[len(playbook_dir):].lstrip("/")
                    break

            # Extract role name if applicable
            role_name = self._extract_role_name(filepath)

            return RawDocument(
                id=self._generate_doc_id(file_url, enriched_content),
                url=file_url,
                title=title,
                content=enriched_content,
                source=self.SOURCE_NAME,
                metadata={
                    "filepath": filepath,
                    "relative_path": rel_path,
                    "file_type": file_type,
                    "role_name": role_name,
                    "size_bytes": len(raw_content),
                    "has_jinja2": "{{" in raw_content or "{%" in raw_content,
                    "modules_used": self._extract_modules(parsed_content) if parsed_content else [],
                },
            )

        except Exception as e:
            logger.error(f"Error reading Ansible file {filepath}: {e}")
            return None

    def _detect_ansible_file_type(
        self, filepath: str, parsed_content: Any
    ) -> str:
        """Detect the type of Ansible file."""
        path_lower = filepath.lower()

        # Check path patterns
        if "/tasks/" in path_lower:
            return "tasks"
        elif "/handlers/" in path_lower:
            return "handlers"
        elif "/vars/" in path_lower or "/defaults/" in path_lower:
            return "variables"
        elif "/meta/" in path_lower:
            return "role_metadata"
        elif "/templates/" in path_lower:
            return "template"
        elif "/files/" in path_lower:
            return "static_file"
        elif "/group_vars/" in path_lower:
            return "group_variables"
        elif "/host_vars/" in path_lower:
            return "host_variables"
        elif "/inventory" in path_lower or "hosts" in path_lower:
            return "inventory"
        elif "/roles/" in path_lower:
            return "role"

        # Check content structure
        if parsed_content:
            if isinstance(parsed_content, list):
                # Check if it looks like a playbook
                if parsed_content and isinstance(parsed_content[0], dict):
                    first_item = parsed_content[0]
                    if "hosts" in first_item or "tasks" in first_item or "roles" in first_item:
                        return "playbook"
                    elif "name" in first_item and any(
                        k in first_item for k in ["copy", "template", "file", "apt", "yum", "service", "command", "shell"]
                    ):
                        return "tasks"

        return "playbook"  # Default

    def _extract_title(
        self, filepath: str, parsed_content: Any, file_type: str
    ) -> str:
        """Extract a meaningful title for the document."""
        import os

        filename = os.path.basename(filepath)
        dirname = os.path.basename(os.path.dirname(filepath))

        # For role files, include role name
        role_name = self._extract_role_name(filepath)
        if role_name:
            if file_type == "tasks":
                return f"Ansible Role: {role_name} - Tasks"
            elif file_type == "handlers":
                return f"Ansible Role: {role_name} - Handlers"
            elif file_type == "variables":
                return f"Ansible Role: {role_name} - Variables"
            elif file_type == "role_metadata":
                return f"Ansible Role: {role_name} - Metadata"
            else:
                return f"Ansible Role: {role_name} - {filename}"

        # For playbooks, try to extract name from content
        if parsed_content and isinstance(parsed_content, list):
            for item in parsed_content:
                if isinstance(item, dict) and "name" in item:
                    return f"Ansible Playbook: {item['name']}"

        # Default to filename
        return f"Ansible: {dirname}/{filename}"

    def _extract_role_name(self, filepath: str) -> Optional[str]:
        """Extract role name from filepath."""
        # Look for /roles/<role_name>/ pattern
        match = re.search(r"/roles/([^/]+)/", filepath)
        if match:
            return match.group(1)
        return None

    def _enrich_content(
        self, filepath: str, raw_content: str, parsed_content: Any, file_type: str
    ) -> str:
        """Enrich content with context for better embedding."""
        lines = []

        # Add header with context
        role_name = self._extract_role_name(filepath)
        if role_name:
            lines.append(f"# Ansible Role: {role_name}\n")
            lines.append(f"## File Type: {file_type}\n")
        else:
            lines.append(f"# Ansible {file_type.replace('_', ' ').title()}\n")

        lines.append(f"## Source: {filepath}\n\n")

        # Add structural analysis if parsed
        if parsed_content:
            if file_type == "playbook" and isinstance(parsed_content, list):
                lines.append("### Playbook Structure:\n")
                for i, play in enumerate(parsed_content):
                    if isinstance(play, dict):
                        name = play.get("name", f"Play {i+1}")
                        hosts = play.get("hosts", "unknown")
                        lines.append(f"- Play: {name} (hosts: {hosts})\n")

                        # List roles used
                        roles = play.get("roles", [])
                        if roles:
                            lines.append("  Roles:\n")
                            for role in roles:
                                role_name = role if isinstance(role, str) else role.get("role", role.get("name", str(role)))
                                lines.append(f"    - {role_name}\n")

                        # Count tasks
                        tasks = play.get("tasks", [])
                        if tasks:
                            lines.append(f"  Tasks: {len(tasks)}\n")

            elif file_type == "tasks" and isinstance(parsed_content, list):
                lines.append("### Tasks:\n")
                modules = set()
                for task in parsed_content:
                    if isinstance(task, dict):
                        name = task.get("name", "Unnamed task")
                        lines.append(f"- {name}\n")
                        # Collect module names
                        for key in task.keys():
                            if key not in ["name", "when", "register", "tags", "vars", "loop", "with_items", "notify", "become", "become_user", "block", "rescue", "always"]:
                                modules.add(key)
                if modules:
                    lines.append(f"\n### Modules Used: {', '.join(sorted(modules))}\n")

            elif file_type == "variables":
                if isinstance(parsed_content, dict):
                    lines.append(f"### Variables Defined: {len(parsed_content)}\n")
                    for var_name in list(parsed_content.keys())[:20]:  # First 20
                        lines.append(f"- {var_name}\n")
                    if len(parsed_content) > 20:
                        lines.append(f"- ... and {len(parsed_content) - 20} more\n")

        lines.append("\n### Raw Content:\n```yaml\n")
        lines.append(raw_content)
        lines.append("\n```\n")

        return "".join(lines)

    def _extract_modules(self, parsed_content: Any) -> List[str]:
        """Extract Ansible module names used in the content."""
        modules = set()

        # Known Ansible module names (common ones)
        known_modules = {
            "copy", "template", "file", "lineinfile", "blockinfile",
            "apt", "yum", "dnf", "package", "pip",
            "service", "systemd", "command", "shell", "raw",
            "user", "group", "authorized_key",
            "git", "get_url", "uri", "fetch", "unarchive",
            "docker_container", "docker_image", "docker_network",
            "k8s", "kubernetes",
            "debug", "fail", "assert", "set_fact", "include_vars",
            "include_tasks", "import_tasks", "include_role", "import_role",
            "wait_for", "pause", "meta",
            "firewalld", "ufw", "iptables",
            "cron", "at", "mount",
            "mysql_db", "mysql_user", "postgresql_db", "postgresql_user",
            "aws_s3", "ec2", "ec2_instance", "cloudformation",
            "azure_rm_virtualmachine", "gcp_compute_instance",
        }

        def extract_from_tasks(tasks):
            if not isinstance(tasks, list):
                return
            for task in tasks:
                if isinstance(task, dict):
                    for key in task.keys():
                        if key in known_modules or key.startswith(("ansible.", "community.", "amazon.", "azure.", "google.")):
                            modules.add(key)
                    # Check block/rescue/always
                    for sub_key in ["block", "rescue", "always"]:
                        if sub_key in task:
                            extract_from_tasks(task[sub_key])

        if isinstance(parsed_content, list):
            for item in parsed_content:
                if isinstance(item, dict):
                    # Playbook with plays
                    if "tasks" in item:
                        extract_from_tasks(item["tasks"])
                    if "pre_tasks" in item:
                        extract_from_tasks(item["pre_tasks"])
                    if "post_tasks" in item:
                        extract_from_tasks(item["post_tasks"])
                    # Task file directly
                    else:
                        extract_from_tasks([item])

        return sorted(list(modules))


def get_fetcher_for_config(config) -> BaseFetcher:
    """
    Get fetcher instance based on SourceConfig.

    Args:
        config: SourceConfig instance

    Returns:
        Appropriate fetcher instance
    """
    fetcher_type = config.fetcher_type

    if fetcher_type == "kubernetes":
        return KubernetesDocsFetcher(
            kubernetes_topics=config.options.get("topics", [])
        )
    elif fetcher_type == "docker":
        return DockerDocsFetcher(
            docker_topics=config.options.get("topics", [])
        )
    elif fetcher_type == "github":
        return GitHubFetcher(
            github_token=config.options.get("github_token")
        )
    elif fetcher_type == "stackoverflow":
        return StackOverflowFetcher()
    elif fetcher_type == "nextjs":
        return NextJSDocsFetcher()
    elif fetcher_type == "python":
        return PythonDocsFetcher(
            python_libraries=config.options.get("libraries", [])
        )
    elif fetcher_type == "local":
        return LocalDocsFetcher(
            docs_dirs=config.options.get("docs_dirs", [])
        )
    elif fetcher_type == "ansible":
        return AnsiblePlaybookFetcher(
            playbook_dirs=config.options.get("playbook_dirs", [])
        )
    else:
        # Use generic fetcher
        return GenericDocsFetcher(
            source_id=config.id,
            base_url=config.base_url,
            sitemap_url=config.sitemap_url,
            url_patterns=config.url_patterns,
            exclude_patterns=config.exclude_patterns,
            max_pages=config.max_pages,
            rate_limit_delay=config.rate_limit_delay,
        )


def get_fetcher(source: str, **kwargs) -> BaseFetcher:
    """
    Get fetcher instance for a source type.

    Args:
        source: Source type name
        **kwargs: Additional arguments for fetcher initialization

    Returns:
        Fetcher instance

    Raises:
        ValueError: If source type is unknown
    """
    fetchers = {
        "nextjs_docs": NextJSDocsFetcher,
        "stack_overflow": StackOverflowFetcher,
        "github": GitHubFetcher,
        "python_docs": PythonDocsFetcher,
        "local_docs": LocalDocsFetcher,
        "docker_docs": DockerDocsFetcher,
        "kubernetes_docs": KubernetesDocsFetcher,
        "ansible_playbooks": AnsiblePlaybookFetcher,
    }

    if source not in fetchers:
        raise ValueError(
            f"Unknown source type: {source}. Available: {list(fetchers.keys())}"
        )

    if source == "python_docs":
        return PythonDocsFetcher(**kwargs)

    if source == "local_docs":
        return LocalDocsFetcher(**kwargs)

    if source == "docker_docs":
        return DockerDocsFetcher(docker_topics=kwargs.get("docker_topics"))

    if source == "kubernetes_docs":
        return KubernetesDocsFetcher(kubernetes_topics=kwargs.get("kubernetes_topics"))

    if source == "ansible_playbooks":
        return AnsiblePlaybookFetcher(playbook_dirs=kwargs.get("ansible_paths"))

    return fetchers[source]()
