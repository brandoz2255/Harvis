"""
Dynamic Source Configuration for RAG Corpus

Provides a flexible, database-backed configuration system for documentation sources.
Sources can be added, modified, or removed via API without code changes.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class SourceCategory(str, Enum):
    """Categories for documentation sources."""
    CODE = "code"           # Complex code/technical - uses high-dim embeddings
    DEVOPS = "devops"       # DevOps/Infrastructure docs
    SECURITY = "security"   # Security/Cyber docs
    GENERAL = "general"     # General documentation


class EmbeddingTier(str, Enum):
    """Embedding model tiers based on complexity needs."""
    HIGH = "high"       # qwen3-embedding (2560 dims) - complex/code
    STANDARD = "standard"  # nomic-embed-text (768 dims) - general docs


# Mapping of tiers to actual models and collections
EMBEDDING_TIER_CONFIG = {
    EmbeddingTier.HIGH: {
        "model": "qwen3-embedding",
        "collection": "local_rag_corpus_code",
        "dimensions": 2560,
        "description": "High-dimensional embeddings for complex technical content"
    },
    EmbeddingTier.STANDARD: {
        "model": "nomic-embed-text",
        "collection": "local_rag_corpus_docs",
        "dimensions": 768,
        "description": "Standard embeddings for general documentation"
    }
}


@dataclass
class SourceConfig:
    """Configuration for a documentation source."""

    id: str                          # Unique identifier (e.g., "ansible_docs")
    name: str                        # Display name (e.g., "Ansible Documentation")
    description: str                 # Brief description
    category: SourceCategory         # Category for grouping
    embedding_tier: EmbeddingTier    # Which embedding model to use
    enabled: bool = True             # Whether source is active

    # Fetcher configuration
    fetcher_type: str = "generic"    # Type of fetcher to use
    base_url: str = ""               # Base documentation URL
    sitemap_url: Optional[str] = None  # Sitemap URL if available

    # Fetcher-specific options
    options: Dict[str, Any] = field(default_factory=dict)

    # Rate limiting
    rate_limit_delay: float = 0.5    # Seconds between requests
    max_pages: int = 100             # Maximum pages to fetch

    # Content filters
    url_patterns: List[str] = field(default_factory=list)  # URL patterns to include
    exclude_patterns: List[str] = field(default_factory=list)  # Patterns to exclude

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["category"] = self.category.value
        data["embedding_tier"] = self.embedding_tier.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceConfig":
        """Create from dictionary."""
        data = data.copy()
        data["category"] = SourceCategory(data.get("category", "general"))
        data["embedding_tier"] = EmbeddingTier(data.get("embedding_tier", "standard"))
        return cls(**data)

    def get_embedding_model(self) -> str:
        """Get the embedding model for this source."""
        return EMBEDDING_TIER_CONFIG[self.embedding_tier]["model"]

    def get_collection(self) -> str:
        """Get the vector collection for this source."""
        return EMBEDDING_TIER_CONFIG[self.embedding_tier]["collection"]


# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULT SOURCE CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_SOURCES: Dict[str, SourceConfig] = {
    # ─── Code/Complex Sources (High-dimensional embeddings) ───────────────────

    "kubernetes_docs": SourceConfig(
        id="kubernetes_docs",
        name="Kubernetes Documentation",
        description="Official Kubernetes documentation - concepts, tasks, references",
        category=SourceCategory.CODE,
        embedding_tier=EmbeddingTier.HIGH,
        fetcher_type="kubernetes",
        base_url="https://kubernetes.io/docs",
        sitemap_url="https://kubernetes.io/en/sitemap.xml",
        options={"topics": ["concepts", "tasks", "reference"]},
        max_pages=150,
    ),

    "github": SourceConfig(
        id="github",
        name="GitHub Repositories",
        description="Code from GitHub repositories",
        category=SourceCategory.CODE,
        embedding_tier=EmbeddingTier.HIGH,
        fetcher_type="github",
        base_url="https://github.com",
        options={"default_repos": ["vercel/next.js"]},
    ),

    "stack_overflow": SourceConfig(
        id="stack_overflow",
        name="Stack Overflow Q&A",
        description="Programming Q&A from Stack Overflow",
        category=SourceCategory.CODE,
        embedding_tier=EmbeddingTier.HIGH,
        fetcher_type="stackoverflow",
        base_url="https://stackoverflow.com",
        options={"default_tags": ["kubernetes", "docker", "python", "devops"]},
    ),

    # ─── DevOps Sources (Standard embeddings) ─────────────────────────────────

    "docker_docs": SourceConfig(
        id="docker_docs",
        name="Docker Documentation",
        description="Official Docker documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="docker",
        base_url="https://docs.docker.com",
        sitemap_url="https://docs.docker.com/sitemap.xml",
        options={"topics": ["engine", "compose", "swarm"]},
    ),

    "ansible_docs": SourceConfig(
        id="ansible_docs",
        name="Ansible Documentation",
        description="Ansible automation platform documentation and playbook guides",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://docs.ansible.com/ansible/latest",
        sitemap_url="https://docs.ansible.com/ansible/latest/sitemap.xml",
        url_patterns=["/docs/", "/playbooks/", "/modules/", "/collections/"],
        exclude_patterns=["/ja/", "/ko/", "/zh/"],  # Exclude non-English
    ),

    "helm_docs": SourceConfig(
        id="helm_docs",
        name="Helm Documentation",
        description="Kubernetes package manager documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://helm.sh/docs",
        sitemap_url="https://helm.sh/sitemap.xml",
        url_patterns=["/docs/"],
    ),

    "terraform_docs": SourceConfig(
        id="terraform_docs",
        name="Terraform Documentation",
        description="HashiCorp Terraform infrastructure as code documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://developer.hashicorp.com/terraform/docs",
        url_patterns=["/terraform/"],
    ),

    "gitlab_docs": SourceConfig(
        id="gitlab_docs",
        name="GitLab Documentation",
        description="GitLab CI/CD and DevOps platform documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://docs.gitlab.com",
        sitemap_url="https://docs.gitlab.com/sitemap.xml",
        url_patterns=["/ee/ci/", "/ee/user/", "/runner/"],
        max_pages=150,
    ),

    "github_actions_docs": SourceConfig(
        id="github_actions_docs",
        name="GitHub Actions Documentation",
        description="GitHub Actions CI/CD workflow documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://docs.github.com/en/actions",
        url_patterns=["/actions/"],
    ),

    "argocd_docs": SourceConfig(
        id="argocd_docs",
        name="ArgoCD Documentation",
        description="GitOps continuous delivery for Kubernetes",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://argo-cd.readthedocs.io/en/stable",
        url_patterns=["/user-guide/", "/operator-manual/", "/getting_started/"],
    ),

    "prometheus_docs": SourceConfig(
        id="prometheus_docs",
        name="Prometheus Documentation",
        description="Prometheus monitoring system documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://prometheus.io/docs",
        url_patterns=["/docs/"],
    ),

    "grafana_docs": SourceConfig(
        id="grafana_docs",
        name="Grafana Documentation",
        description="Grafana observability platform documentation",
        category=SourceCategory.DEVOPS,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://grafana.com/docs/grafana/latest",
        url_patterns=["/docs/grafana/"],
    ),

    # ─── Security/Cyber Sources ───────────────────────────────────────────────

    "mitre_attack": SourceConfig(
        id="mitre_attack",
        name="MITRE ATT&CK",
        description="MITRE ATT&CK framework - adversary tactics and techniques",
        category=SourceCategory.SECURITY,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://attack.mitre.org",
        url_patterns=["/techniques/", "/tactics/", "/mitigations/"],
    ),

    "owasp_docs": SourceConfig(
        id="owasp_docs",
        name="OWASP Documentation",
        description="OWASP security guides and cheat sheets",
        category=SourceCategory.SECURITY,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="generic",
        base_url="https://cheatsheetseries.owasp.org",
        url_patterns=["/cheatsheets/"],
    ),

    # ─── General Documentation ────────────────────────────────────────────────

    "python_docs": SourceConfig(
        id="python_docs",
        name="Python Library Documentation",
        description="Documentation for Python libraries",
        category=SourceCategory.GENERAL,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="python",
        base_url="https://docs.python.org",
        options={"libraries": []},
    ),

    "nextjs_docs": SourceConfig(
        id="nextjs_docs",
        name="Next.js Documentation",
        description="Next.js React framework documentation",
        category=SourceCategory.GENERAL,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="nextjs",
        base_url="https://nextjs.org/docs",
        sitemap_url="https://nextjs.org/sitemap.xml",
    ),

    "local_docs": SourceConfig(
        id="local_docs",
        name="Local Documentation",
        description="Local markdown files and playbooks",
        category=SourceCategory.GENERAL,
        embedding_tier=EmbeddingTier.STANDARD,
        fetcher_type="local",
        base_url="",
        options={"docs_dirs": ["/app/docs", "./docs"]},
    ),
}


class SourceConfigManager:
    """
    Manages source configurations with database persistence.

    Falls back to default configs if database is unavailable.
    """

    def __init__(self, db_pool=None):
        """
        Initialize the config manager.

        Args:
            db_pool: Optional database pool for persistence
        """
        self.db_pool = db_pool
        self._cache: Dict[str, SourceConfig] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize config manager, loading from DB if available."""
        if self._initialized:
            return

        # Start with defaults
        self._cache = {k: v for k, v in DEFAULT_SOURCES.items()}

        # Try to load from database
        if self.db_pool:
            try:
                await self._ensure_table()
                await self._load_from_db()
            except Exception as e:
                logger.warning(f"Could not load configs from DB, using defaults: {e}")

        self._initialized = True
        logger.info(f"Source config manager initialized with {len(self._cache)} sources")

    async def _ensure_table(self) -> None:
        """Ensure the config table exists."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_source_configs (
                    id VARCHAR(64) PRIMARY KEY,
                    config JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

    async def _load_from_db(self) -> None:
        """Load configs from database."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, config FROM rag_source_configs")
            for row in rows:
                try:
                    config = SourceConfig.from_dict(json.loads(row['config']))
                    self._cache[config.id] = config
                except Exception as e:
                    logger.warning(f"Error loading config {row['id']}: {e}")

    async def _save_to_db(self, config: SourceConfig) -> None:
        """Save config to database."""
        if not self.db_pool:
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO rag_source_configs (id, config, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    config = $2::jsonb,
                    updated_at = NOW()
            """, config.id, json.dumps(config.to_dict()))

    async def _delete_from_db(self, source_id: str) -> None:
        """Delete config from database."""
        if not self.db_pool:
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM rag_source_configs WHERE id = $1",
                source_id
            )

    def get_all(self) -> Dict[str, SourceConfig]:
        """Get all source configurations."""
        return self._cache.copy()

    def get(self, source_id: str) -> Optional[SourceConfig]:
        """Get a specific source configuration."""
        return self._cache.get(source_id)

    def get_enabled(self) -> Dict[str, SourceConfig]:
        """Get all enabled sources."""
        return {k: v for k, v in self._cache.items() if v.enabled}

    def get_by_category(self, category: SourceCategory) -> Dict[str, SourceConfig]:
        """Get sources by category."""
        return {k: v for k, v in self._cache.items() if v.category == category}

    def get_by_tier(self, tier: EmbeddingTier) -> Dict[str, SourceConfig]:
        """Get sources by embedding tier."""
        return {k: v for k, v in self._cache.items() if v.embedding_tier == tier}

    async def add(self, config: SourceConfig) -> None:
        """Add a new source configuration."""
        self._cache[config.id] = config
        await self._save_to_db(config)
        logger.info(f"Added source config: {config.id}")

    async def update(self, config: SourceConfig) -> None:
        """Update an existing source configuration."""
        if config.id not in self._cache:
            raise ValueError(f"Source not found: {config.id}")
        self._cache[config.id] = config
        await self._save_to_db(config)
        logger.info(f"Updated source config: {config.id}")

    async def delete(self, source_id: str) -> None:
        """Delete a source configuration."""
        if source_id in self._cache:
            del self._cache[source_id]
            await self._delete_from_db(source_id)
            logger.info(f"Deleted source config: {source_id}")

    async def toggle_enabled(self, source_id: str, enabled: bool) -> None:
        """Enable or disable a source."""
        if source_id not in self._cache:
            raise ValueError(f"Source not found: {source_id}")
        self._cache[source_id].enabled = enabled
        await self._save_to_db(self._cache[source_id])
        logger.info(f"{'Enabled' if enabled else 'Disabled'} source: {source_id}")

    async def reset_to_defaults(self) -> None:
        """Reset all configurations to defaults."""
        self._cache = {k: v for k, v in DEFAULT_SOURCES.items()}

        if self.db_pool:
            async with self.db_pool.acquire() as conn:
                await conn.execute("DELETE FROM rag_source_configs")

        logger.info("Reset source configs to defaults")

    def get_source_model_mapping(self) -> Dict[str, str]:
        """Get mapping of source_id -> embedding_model."""
        return {
            source_id: config.get_embedding_model()
            for source_id, config in self._cache.items()
            if config.enabled
        }

    def get_source_collection_mapping(self) -> Dict[str, str]:
        """Get mapping of source_id -> collection_name."""
        return {
            source_id: config.get_collection()
            for source_id, config in self._cache.items()
            if config.enabled
        }

    def get_valid_source_ids(self) -> List[str]:
        """Get list of all valid source IDs."""
        return list(self._cache.keys())

    def get_enabled_source_ids(self) -> List[str]:
        """Get list of enabled source IDs."""
        return [k for k, v in self._cache.items() if v.enabled]


# Global instance
_config_manager: Optional[SourceConfigManager] = None


async def get_config_manager(db_pool=None) -> SourceConfigManager:
    """Get or create the global config manager."""
    global _config_manager

    if _config_manager is None:
        _config_manager = SourceConfigManager(db_pool)
        await _config_manager.initialize()

    return _config_manager
