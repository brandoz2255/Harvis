"""A document turn keeps the user's own system prompt, and follow-ups on a document stay document turns.

The persona and project instructions are separate system messages; the document prompt is added next to the
question, never in place of them. Follow-ups are tested in several wordings and languages because a miss answers
"make slide 2 shorter" with a prose reply instead of the updated deck.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_completion, doc_bridge  # noqa: E402
from owui_compat.doc_bridge import maybe_prepare_doc_turn  # noqa: E402
from tests.test_doc_revision import _chat, _system  # noqa: E402

PERSONA = "You are Skipper, a pirate. Answer in pirate speak."


def _inject_like_a_chat_turn(body):
    """The prompt steps run_chat_completion applies after the router has prepared a document turn."""
    chat_completion._inject_default_persona(body)
    chat_completion._inject_block_vocabulary(body)


def test_the_users_persona_survives_a_document_turn_and_the_document_prompt_is_added():
    body = {"messages": [{"role": "system", "content": PERSONA},
                         {"role": "user", "content": "make a deck about phishing awareness"}]}
    assert maybe_prepare_doc_turn(body) == "deck"
    _inject_like_a_chat_turn(body)
    systems = _system(body)
    assert systems[0].startswith(PERSONA)
    assert any(doc_bridge.DOC_PROMPT_MARKER in s for s in systems)
    assert body["messages"][-1]["content"] == "make a deck about phishing awareness"


def test_project_instructions_survive_a_document_turn():
    from owui_compat import persistence

    async def folder_prompt(pool, chat_id):
        return "Always cite the CSUSB handbook."

    real = persistence.get_chat_folder_system_prompt
    persistence.get_chat_folder_system_prompt = folder_prompt
    try:
        body = {"chat_id": "c1", "messages": [{"role": "user", "content": "write a report on the lab network"}]}
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
        assert maybe_prepare_doc_turn(body) == "doc"
        asyncio.run(chat_completion._inject_project_instructions(request, body))
        _inject_like_a_chat_turn(body)
    finally:
        persistence.get_chat_folder_system_prompt = real
    systems = _system(body)
    assert systems[0].startswith("Project instructions") and "CSUSB handbook" in systems[0]
    assert any(doc_bridge.DOC_PROMPT_MARKER in s for s in systems)


def test_the_house_persona_bows_out_for_a_document_turn_that_has_no_system_prompt_of_its_own():
    body = {"messages": [{"role": "user", "content": "make a deck about phishing awareness"}]}
    maybe_prepare_doc_turn(body)
    _inject_like_a_chat_turn(body)
    assert len(_system(body)) == 1 and doc_bridge.DOC_PROMPT_MARKER in _system(body)[0]


def test_the_colon_fence_vocabulary_is_not_added_to_a_persona_on_a_document_turn():
    body = {"messages": [{"role": "system", "content": PERSONA},
                         {"role": "user", "content": "make a deck about phishing awareness"}]}
    maybe_prepare_doc_turn(body)
    _inject_like_a_chat_turn(body)
    assert ":::writing" not in body["messages"][0]["content"]
    assert body["messages"][0]["content"] == PERSONA


def test_a_plain_turn_with_a_persona_still_gets_the_vocabulary():
    body = {"messages": [{"role": "system", "content": PERSONA}, {"role": "user", "content": "hello"}]}
    assert maybe_prepare_doc_turn(body) is None
    _inject_like_a_chat_turn(body)
    assert ":::writing" in body["messages"][0]["content"]


# ---- follow-ups after a document -------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "make slide 2 shorter",
    "Add a slide about costs",
    "Make slide 3 punchier, please",
    "haz la diapositiva 2 más corta",
    "añade una diapositiva sobre costes",
    "gracias, ahora acórtalo",
    "ajoute une diapositive sur les coûts",
    "fais-le plus court",
    "mach Folie 2 kürzer",
    "Kannst du eine Folie über Kosten hinzufügen?",
    "请添加一页关于成本的幻灯片",
    "把第二张幻灯片缩短",
])
def test_a_follow_up_right_after_a_document_stays_a_document_turn(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == "deck"
    [prompt] = _system(body)
    assert "REVISION" in prompt and "title: Fire Drill Results" in prompt
    assert body["messages"][-1]["content"] == text


@pytest.mark.parametrize("text", [
    "thanks!",
    "Thanks!!",
    "gracias!",
    "merci beaucoup",
    "danke",
    "谢谢",
    "what does slide 2 say?",
    "slide 2 is too long",
    "¿qué es una diapositiva?",
    "wie füge ich eine Folie hinzu?",
    "comment ajouter une diapositive ?",
    "如何添加幻灯片",
    "borra este archivo",
    "añade esto a mi script",
    "haz una lista de la compra",
])
def test_thanks_questions_and_other_talk_after_a_document_stay_plain_chat(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) is None
    assert _system(body) == []


# English wording that shares stems with the Spanish, French and German reader ("edit", "insert", "reduc",
# "chang", "resum", "section", "page"), and Romance/German topic changes that start with an edit verb and
# carry a definite article: none of them is about the deck.
@pytest.mark.parametrize("text", [
    "edit the function in section 2",
    "insert a section into my essay",
    "include a section about pricing in my thesis",
    "reduce the page count of my thesis",
    "edit page 2 of my website",
    "change the page layout of my website",
    "edit section 3 of my resume",
    "resume the slide show from slide 4",
    "ajoute le lait à ma liste de courses",
    "añade la leche a mi lista de la compra",
    "elimina la cita del calendario",
    "cambia la hora de la reunión",
    "lösche das Foto",
    "quita la alarma de mañana",
    "añade una sección a mi ensayo",
    "ajoute une section à mon CV",
    "füge einen Abschnitt zu meinem Lebenslauf hinzu",
])
def test_topic_changes_that_only_look_like_edits_after_a_document_stay_plain_chat(text):
    for extra in ((), (
        {"role": "user", "content": "what is phishing?"},
        {"role": "assistant", "content": "Phishing is a scam that tricks people into giving up credentials."},
    )):
        body = _chat(text, extra=extra)
        assert maybe_prepare_doc_turn(body) is None
        assert _system(body) == []


@pytest.mark.parametrize("text", [
    "haz la diapositiva 2 más corta",
    "borra la diapositiva 3",
    "cambia el título de la presentación",
    "supprime la diapositive 4",
    "change le titre de la diapositive 1",
    "raccourcis la présentation",
    "streiche die Folie 3",
    "ändere den Titel der Präsentation",
    "hazlo más breve",
    "elimina esto de la diapositiva 5",
])
def test_articles_do_not_stop_a_follow_up_that_names_the_document_from_revising_it(text):
    assert maybe_prepare_doc_turn(_chat(text)) == "deck"
