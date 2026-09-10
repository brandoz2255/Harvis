"""The four hard limits: what a teammate must never do unsupervised.

Each miss here has a real-world cost — a password typed into a page, a card
charged, a mail sent as the user, an account deleted — so the tests are written
as the scenarios rather than as coverage of the regexes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.agents import hard_limits as hl  # noqa: E402


def _refs(**meta):
    return {"r1": meta}


# ─── sign in ─────────────────────────────────────────────────────────────────


def test_typing_into_a_password_box_is_signing_in():
    got = hl.classify("type", {"ref": "r1", "text": "hunter2"}, _refs(type="password", name="pass"))
    assert got == hl.SIGN_IN


def test_clicking_a_sign_in_button_is_signing_in():
    for label in ("Sign in", "Log In", "Continue with Google", "Create account"):
        assert hl.classify("click", {"ref": "r1"}, _refs(name=label)) == hl.SIGN_IN, label


def test_typing_a_one_time_code_is_signing_in():
    assert hl.classify("type", {"ref": "r1", "text": "483920"},
                       _refs(name="otp", type="text")) == hl.SIGN_IN


# ─── pay ─────────────────────────────────────────────────────────────────────


def test_card_number_field_is_paying_not_signing_in():
    assert hl.classify("type", {"ref": "r1", "text": "4111"},
                       _refs(name="cardNumber", type="text")) == hl.PAY


def test_cvv_field_is_paying():
    assert hl.classify("type", {"ref": "r1", "text": "123"}, _refs(name="cvv")) == hl.PAY


def test_place_order_and_confirm_and_pay_are_paying():
    for label in ("Place your order", "Confirm and pay", "Buy now", "Checkout", "Subscribe"):
        assert hl.classify("click", {"ref": "r1"}, _refs(name=label)) == hl.PAY, label


def test_link_to_a_payment_host_is_paying():
    assert hl.classify("click", {"ref": "r1"},
                       _refs(name="Continue", href="https://checkout.stripe.com/x")) == hl.PAY


# ─── send ────────────────────────────────────────────────────────────────────


def test_send_reply_and_post_are_sending():
    for label in ("Send", "Reply all", "Post", "Publish", "Submit review"):
        assert hl.classify("click", {"ref": "r1"}, _refs(name=label)) == hl.SEND, label


def test_enter_key_inside_a_send_control_is_sending():
    assert hl.classify("press", {"ref": "r1", "key": "Enter"}, _refs(name="Send message")) == hl.SEND


# ─── delete ──────────────────────────────────────────────────────────────────


def test_delete_and_close_account_are_deleting():
    for label in ("Delete", "Close account", "Empty trash", "Cancel subscription"):
        assert hl.classify("click", {"ref": "r1"}, _refs(name=label)) == hl.DELETE, label


# ─── what is deliberately NOT a hard limit ───────────────────────────────────


def test_reading_the_page_is_never_a_hard_limit():
    for verb in ("snapshot", "screenshot", "scroll", "back"):
        assert hl.classify(verb, {}, {}) is None, verb


def test_navigating_to_a_login_page_is_not_signing_in():
    # Reaching a page is browsing. Gating it would stop the agent from ever
    # getting to the form and would train the user to approve reflexively.
    assert hl.classify("navigate", {"url": "https://example.com/login"}, {}) is None


def test_ordinary_search_and_typing_are_not_limited():
    assert hl.classify("type", {"ref": "r1", "text": "laptops under 800"},
                       _refs(name="search", type="text")) is None
    assert hl.classify("click", {"ref": "r1"}, _refs(name="Next page")) is None


def test_unknown_ref_does_not_crash_or_flag():
    assert hl.classify("click", {"ref": "nope"}, _refs(name="Send")) is None


# ─── url hints ───────────────────────────────────────────────────────────────


def test_classify_url_flags_payment_hosts_and_paths():
    assert hl.classify_url("https://www.paypal.com/checkout") == hl.PAY
    assert hl.classify_url("https://shop.example.com/checkout") == hl.PAY
    assert hl.classify_url("https://example.com/accounts/login") == hl.SIGN_IN
    assert hl.classify_url("https://example.com/products/42") is None


def test_payment_host_suffix_match_is_not_fooled_by_lookalike():
    # A lookalike domain must not inherit paypal.com's classification.
    assert hl._host_matches("https://notpaypal.com/x", ("paypal.com",)) is False
    assert hl._host_matches("https://www.paypal.com/x", ("paypal.com",)) is True
    # It can still be flagged on its path, which is the intended behaviour:
    # a /pay path is worth suspicion wherever it lives.
    assert hl.classify_url("https://notpaypal.com/pay") == hl.PAY
    assert hl.classify_url("https://notpaypal.com/about") is None


def test_all_four_limits_are_the_only_ones():
    assert set(hl.ALL) == {"sign_in", "pay", "send", "delete"}
