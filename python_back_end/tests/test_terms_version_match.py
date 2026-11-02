"""A signup may only record the house-rules version actually presented."""
import pytest
from fastapi import HTTPException
from plugins.people import terms


def test_rejects_missing_or_stale_version(monkeypatch):
    monkeypatch.setenv('HARVIS_SIGNUP_TERMS', 'on')
    monkeypatch.delenv('HARVIS_HOUSE_RULES', raising=False)
    for version in (None, 'old-version'):
        with pytest.raises(HTTPException) as exc:
            terms.accepted_version(True, 2, version)
        assert exc.value.status_code == 409
    assert terms.accepted_version(True, 2, terms.VERSION) == terms.VERSION
