"""Pure parsing/policy tests: no network, no adapters started."""

import hashlib
import hmac
import json

from messaging_types import Platform
from platforms.base import AdapterSpec, BasePlatformAdapter, split_text
from platforms.email import parse_email
from platforms.matrix import parse_room_event
from platforms.signal import parse_envelope
from platforms.telegram import parse_update
from platforms.whatsapp_cloud import parse_events, verify_signature


class _Dummy(BasePlatformAdapter):
    allowed_users_key = "X_ALLOWED_USERS"

    async def start(self): ...
    async def stop(self): ...
    async def send_text(self, target, text, reply_to_message_id=None): ...


def test_spec_key_and_fingerprint_change_with_env():
    a = AdapterSpec("telegram", 7, {"TELEGRAM_BOT_TOKEN": "1:a"})
    b = AdapterSpec("telegram", 7, {"TELEGRAM_BOT_TOKEN": "1:b"})
    assert a.key == b.key == "telegram:7"
    assert a.fingerprint != b.fingerprint
    assert AdapterSpec("stub", None, source="env").key == "stub:env"
    assert AdapterSpec("x", 1, {"F": " yes "}).flag("F") is True
    assert AdapterSpec("x", 1, {"C": "a, b,,c "}).csv("C") == frozenset({"a", "b", "c"})


def test_allowlisted_sender_maps_to_owner_and_unknown_does_not():
    ad = _Dummy(Platform.STUB, AdapterSpec("stub", 42, {"X_ALLOWED_USERS": "111,222"}))
    assert ad.fallback_user_for("111") == 42
    assert ad.fallback_user_for("999") is None
    env_only = _Dummy(Platform.STUB, AdapterSpec("stub", None, {"X_ALLOWED_USERS": "111"}, source="env"))
    assert env_only.fallback_user_for("111") is None


def test_status_never_contains_secret():
    ad = _Dummy(Platform.STUB, AdapterSpec("stub", 1, {"TOKEN": "super-secret-value"}))
    ad._mark_error("bad token")
    assert "super-secret-value" not in json.dumps(ad.status())
    assert ad.status()["state"] == "error"


def test_split_text_prefers_newlines_then_words():
    text = "a" * 10 + "\n" + "b" * 10 + " " + "c" * 10
    chunks = split_text(text, 15)
    assert chunks == ["a" * 10, "b" * 10, "c" * 10]
    assert split_text("x" * 40, 15) == ["x" * 15, "x" * 15, "x" * 10]


# ---------------------------------------------------------------- telegram

def _tg(chat_type="private", text="hi", reply_from=None, **extra):
    m = {"message_id": 5, "chat": {"id": 99, "type": chat_type}, "from": {"id": 7, "first_name": "Ann", "is_bot": False},
         "text": text, **extra}
    if reply_from is not None:
        m["reply_to_message"] = {"from": {"id": reply_from}}
    return {"update_id": 1, "message": m}


def test_telegram_private_always_passes_and_groups_need_mention():
    p = parse_update(_tg(), bot_id=1, bot_username="harvisbot")
    assert p["chat_id"] == "99" and p["sender_id"] == "7" and p["is_dm"] is True and p["text"] == "hi"
    assert parse_update(_tg("supergroup", "hello all"), bot_id=1, bot_username="harvisbot") is None
    p = parse_update(_tg("supergroup", "@HarvisBot what time?"), bot_id=1, bot_username="harvisbot")
    assert p["text"] == "what time?" and p["is_dm"] is False
    p = parse_update(_tg("group", "and you?", reply_from=1), bot_id=1, bot_username="harvisbot")
    assert p["text"] == "and you?"


def test_telegram_ignores_bots_edits_and_empty():
    bot = _tg()
    bot["message"]["from"]["is_bot"] = True
    assert parse_update(bot, bot_id=1, bot_username="b") is None
    assert parse_update({"update_id": 2, "edited_message": _tg()["message"]}, bot_id=1, bot_username="b") is None
    assert parse_update(_tg(text=""), bot_id=1, bot_username="b") is None
    topic = parse_update(_tg(is_topic_message=True, message_thread_id=33), bot_id=1, bot_username="b")
    assert topic["thread_id"] == "33"


# ------------------------------------------------------------------ matrix

def _mx(body, sender="@ann:hs", mentions=None, rel=None):
    content = {"msgtype": "m.text", "body": body}
    if mentions:
        content["m.mentions"] = {"user_ids": mentions}
    if rel:
        content["m.relates_to"] = rel
    return {"type": "m.room.message", "sender": sender, "event_id": "$e1", "content": content}


def test_matrix_dm_passes_group_needs_mention_own_ignored():
    me = "@harvis:hs"
    assert parse_room_event("!r", _mx("hi"), self_user_id=me, self_display="Harvis", is_dm=True)["text"] == "hi"
    assert parse_room_event("!r", _mx("hi"), self_user_id=me, self_display="Harvis", is_dm=False) is None
    p = parse_room_event("!r", _mx("Harvis: status?", mentions=[me]), self_user_id=me, self_display="Harvis", is_dm=False)
    assert p["text"] == "status?" and p["sender_display_name"] == "ann"
    assert parse_room_event("!r", _mx("x", sender=me), self_user_id=me, self_display=None, is_dm=True) is None
    edit = _mx("* fixed", rel={"rel_type": "m.replace", "event_id": "$e0"})
    assert parse_room_event("!r", edit, self_user_id=me, self_display=None, is_dm=True) is None


# ------------------------------------------------------------------- email

def _mail(frm="Ann <ann@example.com>", subject="Question", body="What is up?\n\n> quoted\n", **headers):
    lines = [f"From: {frm}", f"To: harvis@example.com", f"Subject: {subject}", "Message-ID: <m1@example.com>"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n" + body).encode()


def test_email_parses_sender_subject_and_strips_quotes():
    p = parse_email(_mail())
    assert p["sender_id"] == "ann@example.com"
    assert p["sender_display_name"] == "Ann"
    assert p["text"] == "What is up?"
    assert p["message_id"] == "<m1@example.com>" and p["references"] == ["<m1@example.com>"]


def test_email_skips_automated_senders():
    assert parse_email(_mail(frm="noreply@shop.com")) is None
    assert parse_email(_mail(**{"Auto-Submitted": "auto-replied"})) is None
    assert parse_email(_mail(**{"Precedence": "bulk"})) is None
    assert parse_email(_mail(**{"List-Id": "<dev.lists.example.com>"})) is None


# ----------------------------------------------------------- whatsapp cloud

def _wa(phone_id="PHONE1", messages=None):
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id},
        "contacts": [{"wa_id": "15551234567", "profile": {"name": "Ann"}}],
        "messages": messages if messages is not None else [
            {"from": "15551234567", "id": "wamid.1", "type": "text", "text": {"body": "hello"}}],
    }}]}]}


def test_whatsapp_routes_by_phone_number_id():
    ours, msgs = parse_events(_wa(), "PHONE1")
    assert ours and msgs[0]["sender_display_name"] == "Ann" and msgs[0]["text"] == "hello"
    ours, msgs = parse_events(_wa("OTHER"), "PHONE1")
    assert not ours and msgs == []
    ours, msgs = parse_events(_wa(messages=[]), "PHONE1")  # a status-only event
    assert ours and msgs == []


def test_whatsapp_signature_check():
    raw = b'{"x":1}'
    good = "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    assert verify_signature(raw, good, "secret")
    assert not verify_signature(raw, good, "other")
    assert not verify_signature(raw, "nope", "secret")


# ------------------------------------------------------------------ signal

def _sig(text="hey", source="+15550001111", group=None, mentions=None, wrap="sse"):
    data = {"message": text, "timestamp": 1700000000000}
    if group:
        data["groupInfo"] = {"groupId": group}
    if mentions:
        data["mentions"] = mentions
    env = {"sourceNumber": source, "sourceName": "Ann", "timestamp": 1700000000000, "dataMessage": data}
    return {"envelope": env} if wrap == "sse" else {"jsonrpc": "2.0", "method": "receive", "params": {"envelope": env}}


def test_signal_dm_group_mention_and_own_messages():
    me = "+15559999999"
    p = parse_envelope(_sig(), account=me)
    assert p["chat_id"] == "+15550001111" and p["is_dm"] and p["text"] == "hey"
    assert parse_envelope(_sig(wrap="rpc"), account=me)["sender_display_name"] == "Ann"
    assert parse_envelope(_sig(group="g1"), account=me) is None
    p = parse_envelope(_sig("￼ ping", group="g1", mentions=[{"number": me}]), account=me)
    assert p["chat_id"] == "g1" and p["text"] == "ping" and p["is_dm"] is False
    assert parse_envelope(_sig(source=me), account=me) is None
