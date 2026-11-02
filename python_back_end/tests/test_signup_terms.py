"""House rules on the sign-up form (plugins/people/terms.py)."""
import pytest
from fastapi import HTTPException

from owui_compat import config as owui_config
from owui_compat.schemas import OwuiSignupBody
from plugins.people import terms


@pytest.mark.parametrize("exposure,env,expected", [
    ("local", "", False),
    ("lan", "", True),
    ("tunnel", "", True),
    ("local", "on", True),
    ("lan", "off", False),
])
def test_rules_follow_exposure(monkeypatch, exposure, env, expected):
    monkeypatch.setenv("HARVIS_EXPOSURE", exposure)
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", env)
    assert terms.terms_required() is expected


def test_sign_up_without_ticking_is_refused(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    with pytest.raises(HTTPException) as err:
        terms.accepted_version(False, user_count=3)
    assert err.value.status_code == 400
    assert terms.accepted_version(True, user_count=3, presented_version=terms.VERSION) == terms.VERSION


def test_hosts_first_account_and_laptop_accept_nothing(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    assert terms.accepted_version(False, user_count=0) is None
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "off")
    assert terms.accepted_version(False, user_count=3) is None


def test_config_lists_rules_only_when_asked(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    monkeypatch.delenv("HARVIS_HOUSE_RULES", raising=False)
    shown = owui_config.build_config(onboarding=False)["features"]["terms"]
    assert shown["required"] is True
    assert shown["version"] == terms.VERSION
    assert shown["points"] == list(terms.POINTS)
    # Onboarding: the first account is the host's own.
    assert owui_config.build_config(onboarding=True)["features"]["terms"]["required"] is False
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "off")
    assert owui_config.build_config(onboarding=False)["features"]["terms"] == {
        "required": False, "version": None, "points": []}


def test_signup_body_defaults_to_not_accepted():
    body = OwuiSignupBody(name="a", email="a@b.c", password="secret1")
    assert body.accept_terms is False
    assert OwuiSignupBody(name="a", email="a@b.c", password="secret1", accept_terms=True).accept_terms


def test_host_can_supply_its_own_rules(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    monkeypatch.setenv("HARVIS_HOUSE_RULES", "Be kind. |  | Ask before   big downloads. ")
    version, points = terms.rules()
    assert points == ["Be kind.", "Ask before big downloads."]
    assert version.startswith(terms.VERSION + "+")
    assert terms.accepted_version(True, user_count=2, presented_version=version) == version
    monkeypatch.setenv("HARVIS_HOUSE_RULES", "Be kind.")
    assert terms.rules()[0] != version  # changed rules are new rules


def test_blank_custom_rules_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("HARVIS_HOUSE_RULES", " | ")
    assert terms.rules() == (terms.VERSION, list(terms.POINTS))
