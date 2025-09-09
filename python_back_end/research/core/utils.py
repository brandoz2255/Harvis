# python_back_end/research/core/utils.py
import time
import re
import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import tldextract
import functools
import logging

logger = logging.getLogger(__name__)

# ----- URL canonicalization -----

UTM_PREFIXES = ("utm_", "gclid", "fbclid", "mc_cid", "mc_eid")

def canonicalize_url(url: str) -> str:
    """
    Normalize a URL for deduplication.
    Removes tracking params and normalizes host/path.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        ext = tldextract.extract(host)
        host = ".".join([p for p in [ext.subdomain, ext.domain, ext.suffix] if p])
        path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
        query = urlencode(
            [
                (k, v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if not any(k.startswith(p) for p in UTM_PREFIXES)
            ],
            doseq=True,
        )
        return urlunsplit((parts.scheme or "https", host, path, query, ""))
    except Exception as e:
        logger.warning(f"canonicalize_url failed: {e}")
        return url

def compute_hash(text: str) -> str:
    """
    Compute SHA256 hash of a string.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# ----- Retry decorator -----

def retry(times: int = 3, delay: float = 1.0, backoff: float = 2.0, exceptions=(Exception,)):
    """
    Retry a function call with exponential backoff.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _delay = delay
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == times - 1:
                        raise
                    logger.warning(f"{func.__name__} failed (attempt {attempt+1}/{times}): {e}")
                    time.sleep(_delay)
                    _delay *= backoff
        return wrapper
    return decorator

# ----- Simple timer -----

class Timer:
    """
    Context manager for measuring elapsed time.
    """
    def __init__(self, label: str = "Timer"):
        self.label = label
        self.start = None
        self.elapsed = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed = time.time() - self.start
        logger.info(f"{self.label} took {self.elapsed:.2f}s")