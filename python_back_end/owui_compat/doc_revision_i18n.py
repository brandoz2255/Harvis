"""Edit requests on a document, in Spanish, French, German and Chinese.

doc_revision reads English wording. "haz la diapositiva 2 más corta" has no English
word in it, so without this the follow-up falls to plain chat and the model answers
in prose. Same rule as the English reader: a miss costs one prose answer, a false hit
answers a question with a document, so a request must open with an edit verb and name
a part of the document (or point at it with a pronoun). Thanks, questions and
software talk stay unclaimed.

English belongs to doc_revision: the stems below ("edit", "insert", "reduc", "chang", "resum") and nouns
("section", "page", "document") are English words too, so a message with an English function word in it is
left alone here, and so is a verb that takes a possessive object that is not a document ("añade una sección a
mi ensayo"), as the English reader does.

Words are matched with accents removed ("añade" is "anade"), as stems of the first
word so that imperatives, infinitives and attached pronouns ("acórtalo") all hit.
"""

from __future__ import annotations

import re
import unicodedata

MAX_EDIT_CHARS = 400

_EDIT_STEMS = (
    # es
    "anad", "agreg", "quit", "elimin", "borr", "cambi", "reemplaz", "sustitu", "acort", "alarg", "ampli",
    "simplific", "mejor", "corrig", "reescrib", "traduc", "inclu", "insert", "reduc", "renombr", "actualiz",
    "reorden", "mueve", "mover", "resum", "ajust", "modific", "edit", "reformul", "resalt",
    # fr
    "ajout", "supprim", "enlev", "retir", "chang", "remplac", "raccourc", "allong", "rallong", "simplifi",
    "amelior", "reecri", "traduis", "traduir", "reduis", "renomm", "mets", "metz", "condens", "developp",
    "etoff", "reformul", "ajust", "modifi", "deplac", "reorgan",
    # de
    "fug", "erganz", "entfern", "losch", "ander", "ersetz", "verlanger", "vereinfach", "verbesser", "korrigier",
    "ubersetz", "bearbeit", "umschreib", "streich", "aktualisier", "uberarbeit", "kurze", "verkurz", "erweiter",
    "formulier", "anpass", "hinzufug", "nimm", "tausch", "verschieb",
)
_MAKE_STEMS = ("haz", "hacer", "pon", "fais", "faire", "rends", "rendre", "mach", "mache", "machen")

_NOUN_STEMS = (
    "diapositiv", "slide", "seccion", "tabla", "fila", "columna", "titulo", "subtitulo", "presentacion",
    "documento", "informe", "hoja", "grafico", "resumen", "introduccion", "conclusion", "parrafo",
    "pagina", "esquema", "cronologia",
    "section", "tableau", "ligne", "colonne", "titre", "sous-titre", "document", "rapport", "feuille", "graphique",
    "presentation", "resume", "paragraphe", "page", "chronologie", "tableur",
    "folie", "abschnitt", "tabelle", "zeile", "spalte", "titel", "prasentation", "dokument", "bericht",
    "diagramm", "zusammenfassung", "einleitung", "fazit", "absatz", "seite", "gliederung", "kapitel",
)
# Not "la", "le", "los", "las", "das", "ce", "todo": those are mostly articles ("elimina la cita", "lösche das Foto").
_PRONOUN_TOKENS = frozenset(("lo", "esto", "eso", "cela", "ca", "dies", "ihn", "es"))
# Words that no Spanish, French or German message uses; "a", "in", "an", "on" are left out on purpose.
_ENGLISH = frozenset((
    "the", "my", "of", "to", "into", "with", "your", "our", "from", "about", "this", "that", "these", "those",
    "it", "its", "and", "please", "you", "how", "what", "is", "are"))
# "mi ensayo", "ma liste", "mein Lebenslauf": a possessive that does not point at a part of the document.
_POSSESSIVE = re.compile(
    r"\b(?:mi|mis|tu|tus|su|sus|nuestro|nuestra|mon|ma|mes|ton|ta|tes|son|sa|ses|notre|nos|votre|vos|"
    r"mein\w*|dein\w*|sein\w*|unser\w*)\s+((?:[a-z0-9'-]+\s+){0,2}[a-z0-9'-]+)")
_COMPARATIVE = re.compile(
    r"\b(?:mas|menos|plus|moins|mehr|weniger)\s+\w+|\b(?:corto|corta|cortos|cortas|largo|larga|breve|court|courte|"
    r"longue|long|kurzer|langer|einfacher|formeller|knapper|klarer|ausfuhrlicher|professioneller|kompakter|"
    r"ubersichtlicher|lockerer|praziser|detaillierter|visueller|besser|mejor|mieux|meilleur|meilleure)\b")
_POLITE = re.compile(
    r"^(?:(?:gracias|vale|ok|okay|bien|genial|perfecto|ahora|tambien|y|por\s+favor|puedes|podrias|pudieras|"
    r"merci|d'accord|super|parfait|maintenant|aussi|et|s'il\s+(?:te|vous)\s+plait|stp|peux-tu|pourrais-tu|"
    r"peux\s+tu|pourrais\s+tu|pouvez-vous|tu\s+peux|danke|gut|prima|jetzt|auch|und|bitte|kannst\s+du|"
    r"konntest\s+du|konnen\s+sie)[\s,.!;:¡¿-]+)+")
_GERMAN_POLITE = re.compile(r"^(?:kannst\s+du|konntest\s+du|konnen\s+sie)\b")
_SOFTWARE = frozenset((
    "codigo code script error errores archivo fichier fehler datei contrasena programa funcion fonction "
    "funktion servidor serveur base python javascript linux git docker").split())
# "hazlo", "acórtalo", "fais-le": the pronoun is attached to the verb.
_CLITIC = re.compile(r"(?:lo|la|los|las|-le|-la|-les)$")
_PASTED = re.compile(r"^[^:\n]{0,200}:[ \t]*\S|^[^:\n]{0,200}:[ \t]*\n\s*\S")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n|[¡¿]")

_ZH_VERB = re.compile(r"添加|增加|加上|新增|删除|删掉|去掉|修改|缩短|精简|简化|改短|改长|加长|翻译|重写|替换|调整|改成|改为|更换")
_ZH_NOUN = re.compile(r"幻灯片|页|节|章节|表格|文档|报告|演示|ppt|标题|摘要|总结|图表|段落|列表|大纲")
_ZH_QUESTION = re.compile(r"如何|怎么|怎样|什么|吗|\?|？|为什么|能不能解释")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("’", "'"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _tokens(clause: str) -> list[str]:
    return re.findall(r"[a-z0-9'-]+", clause)


def _has_noun(tokens: list[str]) -> bool:
    return any(t.startswith(_NOUN_STEMS) for t in tokens)


def _clause(text: str) -> str:
    """The first sentence that is a request: leading thanks and politeness are skipped."""
    for sentence in _SENTENCE_SPLIT.split(_plain(text).strip()):
        rest = _POLITE.sub("", sentence.strip()).strip(" ,.!;:")
        if rest:
            return rest
    return ""


def _chinese(text: str) -> bool:
    if not re.search(r"[一-鿿]", text):
        return False
    lowered = text.lower()
    return bool(_ZH_VERB.search(lowered) and _ZH_NOUN.search(lowered) and not _ZH_QUESTION.search(lowered))


def _english(tokens: list[str]) -> bool:
    return bool(set(tokens) & _ENGLISH)


def _other_document(clause: str) -> bool:
    return any(not _has_noun(_tokens(m.group(1))) for m in _POSSESSIVE.finditer(clause))


def names_part(text: str) -> bool:
    """The message names a piece of the document ("la diapositiva 2", "die Folie") in one of the languages."""
    if not isinstance(text, str):
        return False
    if _chinese(text):
        return True
    tokens = _tokens(_clause(text))
    return _has_noun(tokens) and not _english(tokens)


def is_edit(text: str) -> bool:
    """Reads like a change request to a document, in Spanish, French, German or Chinese."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_EDIT_CHARS:
        return False
    if _chinese(text):
        return True
    clause = _clause(text)
    tokens = _tokens(clause)
    if not tokens or _english(tokens) or set(tokens) & _SOFTWARE or _other_document(clause):
        return False
    named = _has_noun(tokens)
    first = tokens[0]
    pointed = named or bool(set(tokens[1:]) & _PRONOUN_TOKENS) or bool(_CLITIC.search(first))
    pasted = _PASTED.match(_plain(text).strip())
    if pasted and not named:
        return False
    if first.startswith(_MAKE_STEMS) and _COMPARATIVE.search(clause):
        return pointed
    if first.startswith(_EDIT_STEMS):
        return pointed
    # "Kannst du eine Folie über Kosten hinzufügen?": the verb comes last.
    if _GERMAN_POLITE.match(_plain(text).strip()):
        return named and any(t.startswith(_EDIT_STEMS) for t in tokens)
    return False
