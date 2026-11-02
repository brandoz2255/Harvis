"""The output-language instruction added to notebook prompts."""
import re
from typing import Optional

from .chat_config import MAX_LANGUAGE_CHARS

# A language name or tag ("Spanish", "Português (Brasil)", "zh-CN"); anything else is not a language.
_LANGUAGE = re.compile(r"^[^\W\d_][\w .()'-]{0,39}$", re.UNICODE)


def clean_language(lang: Optional[str]) -> str:
    """The language name if it looks like one, else ''."""
    text = " ".join((lang or "").split())
    return text if text and len(text) <= MAX_LANGUAGE_CHARS and _LANGUAGE.match(text) else ""


def language_clause(lang: Optional[str]) -> str:
    """One sentence telling the model what language to answer in; '' when unset."""
    name = clean_language(lang)
    if not name:
        return ""
    return (
        f"Write your answer in {name}, whatever language the question or the sources use. "
        "Short quotations from the sources may stay in their original language."
    )
