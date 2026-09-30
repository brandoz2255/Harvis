"""A page trafilatura can't read falls back cleanly instead of raising.

Deep research lost every such page to ``HtmlExtractionResult.__init__() got an
unexpected keyword argument 'test'``: the fallback's empty result misspelled
``text``, and the ``readability`` import was misspelled too, so the fallback
always took that broken branch.
"""
from research.extract import html_trafilatura as ht


def test_fallback_without_readability_returns_an_empty_result(monkeypatch):
    monkeypatch.setattr(ht, "Document", None)

    res = ht.readablity_fallback("<html><body></body></html>")

    assert (res.title, res.text) == ("", "")


def test_unreadable_page_is_a_plain_miss_not_an_error(monkeypatch):
    monkeypatch.setattr(ht, "Document", None)
    monkeypatch.setattr(ht, "_trafilatura_extract",
                        lambda html: ht.HtmlExtractionResult(title="", text="", language=None, meta={}))

    out = ht.extract_html("https://example.org/x", "<html></html>", user_agent="t", timeout_s=5)

    assert out["success"] is False
    assert "error" not in out["meta"]
