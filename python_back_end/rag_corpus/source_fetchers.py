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
                }
            )
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    @abstractmethod
    async def fetch(
        self,
        keywords: List[str],
        extra_urls: List[str]
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
        self,
        keywords: List[str],
        extra_urls: List[str]
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
        self,
        session: aiohttp.ClientSession,
        url: str
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
                title = title_tag.get_text(strip=True) if title_tag else "Next.js Documentation"
                
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
                for tag in main_content.find_all(["script", "style", "nav", "footer", "aside", "header"]):
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
                    }
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
        self,
        keywords: List[str],
        extra_urls: List[str]
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
        self,
        session: aiohttp.ClientSession,
        tag: str,
        page_size: int = 20
    ) -> List[Dict]:
        """Search for questions by tag."""
        params = {
            "order": "desc",
            "sort": "votes",
            "tagged": tag,
            "site": "stackoverflow",
            "filter": "withbody",
            "pagesize": page_size
        }
        
        async with session.get(f"{self.API_BASE}/questions", params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("items", [])
            else:
                logger.warning(f"SO API returned {resp.status}")
                return []
    
    async def _fetch_question_with_answers(
        self,
        session: aiohttp.ClientSession,
        question: Dict
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
            "filter": "withbody"
        }
        
        answers = []
        try:
            async with session.get(f"{self.API_BASE}/questions/{q_id}/answers", params=params) as resp:
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
            }
        )
    
    async def _fetch_question_by_id(
        self,
        session: aiohttp.ClientSession,
        question_id: int
    ) -> Optional[RawDocument]:
        """Fetch a specific question by ID."""
        params = {
            "site": "stackoverflow",
            "filter": "withbody"
        }
        
        async with session.get(f"{self.API_BASE}/questions/{question_id}", params=params) as resp:
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
                timeout=aiohttp.ClientTimeout(total=30),
                headers=headers
            )
        return self._session
    
    async def fetch(
        self,
        keywords: List[str],
        extra_urls: List[str]
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
        self,
        session: aiohttp.ClientSession,
        keywords: List[str]
    ) -> List[str]:
        """Search for repositories by keywords."""
        query = " ".join(keywords) + " language:typescript language:javascript"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": 10
        }
        
        repos = []
        try:
            async with session.get(f"{self.API_BASE}/search/repositories", params=params) as resp:
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
        path: str = ""
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
        self,
        session: aiohttp.ClientSession,
        repo: str,
        item: Dict,
        keywords: List[str]
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
                        "file_type": file_path.split(".")[-1] if "." in file_path else "unknown",
                        "size": item.get("size", 0),
                    }
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
        python_libraries: Optional[List[str]] = None
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
            if any(host in url for host in self.DOCS_HOSTS + ["python.org", "palletsprojects.com", "pydata.org"]):
                try:
                    doc = await self._fetch_doc_page(session, url, "custom")
                    if doc:
                        documents.append(doc)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")
        
        logger.info(f"Fetched {len(documents)} Python documentation pages")
        return documents
    
    async def _fetch_library_docs(
        self,
        session: aiohttp.ClientSession,
        library: str
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
        self,
        session: aiohttp.ClientSession,
        library: str
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
        self,
        session: aiohttp.ClientSession,
        library: str
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
                        if any(k in key_lower for k in ["doc", "document", "guide", "reference"]):
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
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        library: str
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
                        if "#" not in href and not any(skip in href for skip in [
                            "/search", "/genindex", "/py-modindex", "/_", "/edit/",
                            ".zip", ".tar", ".pdf", ".png", ".jpg", ".svg"
                        ]):
                            links.add(href)
                
        except Exception as e:
            logger.warning(f"Could not find doc links: {e}")
        
        return links
    
    async def _fetch_doc_page(
        self,
        session: aiohttp.ClientSession,
        url: str,
        library: str
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
                title = title_tag.get_text(strip=True) if title_tag else f"{library} Documentation"
                
                # Extract main content
                main = (
                    soup.find("main") or
                    soup.find("article") or
                    soup.find("div", {"role": "main"}) or
                    soup.find("div", class_=re.compile(r"document|content|body"))
                )
                
                if not main:
                    main = soup.find("body")
                
                if not main:
                    return None
                
                # Remove unwanted elements
                for tag in main.find_all(["script", "style", "nav", "aside", "footer", "header"]):
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
                    }
                )
                
        except Exception as e:
            logger.error(f"Error fetching doc page {url}: {e}")
            return None
    
    def _extract_doc_content(self, element) -> str:
        """Extract text content preserving structure."""
        lines = []
        
        for child in element.descendants:
            if hasattr(child, 'name'):
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
    }
    
    if source not in fetchers:
        raise ValueError(f"Unknown source type: {source}. Available: {list(fetchers.keys())}")
    
    if source == "python_docs":
        return PythonDocsFetcher(**kwargs)
    
    return fetchers[source]()

