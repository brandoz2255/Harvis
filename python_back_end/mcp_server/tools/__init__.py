from .search_code import register_search_code
from .search_cyber import register_search_cyber
from .search_linux import register_search_linux
from .search_all import register_search_all
from .get_sources import register_get_source_list


def register_all_tools():
    """Register all RAG tools."""
    register_search_code()
    register_search_cyber()
    register_search_linux()
    register_search_all()
    register_get_source_list()
