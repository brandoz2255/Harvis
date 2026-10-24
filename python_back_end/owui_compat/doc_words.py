"""Wording tables shared by the document detector and the follow-up reader.

doc_bridge decides whether a message asks for a new deck, document, spreadsheet or PDF;
doc_revision decides whether it edits or converts the one already in the chat. Both read
the user's words through ``normalize`` so that "slide show", "power point" and a mistyped
"sildeshow" mean the same thing to each. The tables live here because doc_bridge imports
doc_revision: a shared helper inside doc_bridge would be a circular import.

``foreign_hit`` is the small first-turn reader for Spanish, French, German, Portuguese,
Italian, Dutch and Chinese ("hazme una presentacion"). Like the English reader it needs a
request verb at the start of the clause, so a question about a presentation is left alone.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Common misspellings of the nouns that name a format, mapped to the word the readers know.
TYPOS = {
    "sildeshow": "slideshow", "slidshow": "slideshow", "slideshw": "slideshow", "slidesow": "slideshow",
    "slidehsow": "slideshow", "sldeshow": "slideshow", "slidshows": "slideshows",
    "powerpint": "powerpoint", "powrpoint": "powerpoint", "powerpiont": "powerpoint", "pwerpoint": "powerpoint",
    "powerpoit": "powerpoint", "powerpionts": "powerpoints",
    "speadsheet": "spreadsheet", "spreedsheet": "spreadsheet", "spredsheet": "spreadsheet",
    "spreadshet": "spreadsheet", "spreadsheat": "spreadsheet",
    "presention": "presentation", "presentaion": "presentation", "presentaton": "presentation",
    "pesentation": "presentation", "presenation": "presentation",
    "excell": "excel", "pdff": "pdf",
}
_TYPO_RE = re.compile(r"\b(" + "|".join(sorted(TYPOS, key=len, reverse=True)) + r")\b")

# A construction deck or a playground slide names a thing, not a file, but only when the phrase ends
# the clause ("build a deck for my house"). "a deck on the pool party" and "add a slide on the
# playground safety rules" still have a topic after the place word, so they are left alone.
_CLAUSE_END = r"(?=\s*(?:[.,!?;:\n]|$)|\s+(?:please|pls|thanks|thx|now|asap)\b)"

# Phrases rewritten to one token before the words are read. The first rows take the deck sense
# out of a deck that is not a slide deck, so the rest of the detector never sees it.
PHRASES = (
    (re.compile(r"\b(?:patio|wood(?:en)?|backyard|pool|roof|boat|ship'?s?)\s+decks?\b"), "terrace"),
    (re.compile(r"\bdecks?\s+(?:for|on|around)\s+(?:my|the|our)\s+(?:house|home|yard|backyard|pool|cabin)"
                + _CLAUSE_END), "terrace"),
    (re.compile(r"\bcards?\s+decks?\b|\bdecks?\s+of\s+cards?\b"), "cardgame"),
    (re.compile(r"\b(?:playground|water|garden|park)\s+slides?\b"
                r"|\bslides?\s+(?:on|at|in)\s+(?:the|a|my)\s+(?:playground|park|pool)" + _CLAUSE_END), "terrace"),
    (re.compile(r"\b(?:cheat|fact|info|study)[\s-]*(?:sheet|guide)s?\b"), "handout"),
    (re.compile(r"\bone[\s-]*pagers?\b"), "onepager"),
    (re.compile(r"\bwrite[\s-]*ups?\b"), "writeup"),
    (re.compile(r"\bword\s+(?:docs?|documents?|files?)\b"), "docx"),
    (re.compile(r"\bgoogle\s+(?:docs?|documents?)\b"), "document"),
    (re.compile(r"\bgoogle\s+slides\b"), "slides"),
    (re.compile(r"\bgoogle\s+sheets?\b"), "spreadsheet"),
    (re.compile(r"\b(?:slide|pitch)[\s-]*decks?\b"), "deck"),
    (re.compile(r"\bslides?[\s-]+shows?\b"), "slideshow"),
    (re.compile(r"\bpower[\s-]+points?\b"), "powerpoint"),
)

# Rewrites that take a spreadsheet sense out of a phrase. The follow-up reader keeps these words
# (it must still see "update the balance sheet" as a sheet edit), so it skips this group.
SHEET_PHRASES = (
    (re.compile(r"\b(?:style|answer|time|balance)[\s-]*sheets?\b"), "stylesheet"),
    (re.compile(r"\btracker\s+tables?\b"), "tracker"),
)


def normalize(text: str, *, sheets: bool = True) -> str:
    """Lower-cased text with typos fixed and format phrases rewritten to single words.

    ``sheets=False`` leaves "balance sheet", "time sheet" and "tracker table" as written.
    """
    text = (text or "").lower().replace("’", "'")
    text = _TYPO_RE.sub(lambda m: TYPOS[m.group(1)], text)
    for pattern, repl in PHRASES + (SHEET_PHRASES if sheets else ()):
        text = pattern.sub(repl, text)
    return text


# ---- first-turn requests in other languages ----------------------------------------------------

def _fold(text: str) -> str:
    """Lower-case with accents removed and hyphens and apostrophes read as spaces."""
    text = unicodedata.normalize("NFD", normalize(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[-'’]+", " ", text)


_POLITE = (r"(?:(?:por favor|please|bitte|s il (?:te|vous) plait|puedes|podrias|me puedes|peux tu|pouvez vous|"
           r"pourrais tu|kannst du|kannst du mir|konntest du|puoi|kun je|voce pode)\s+)*")
# Request verbs that take the thing itself: "hazme una presentacion", "fais moi un rapport".
_MAKE_VERBS = (
    r"hazme|haz|hacer|creame|crea|crear|generame|genera|generar|preparame|prepara|escribeme|escribe|"
    r"redactame|redacta|disename|disena|"
    r"fais moi|fais|faire|creer|cree|generer|genere|ecrire|ecris|redige|"
    r"erstelle|erstell|mach mir|mache|mach|schreibe|schreib|generiere|"
    r"crie|faca|faz|gere|escreva|"
    r"fai|scrivi|"
    r"maak me|maak|schrijf|genereer"
)
# Want verbs name a need, which may be for anything: "quiero abrir un pdf" wants no document made.
# They count only when the thing wanted follows directly, or a make verb comes next.
_WANT_VERBS = (
    r"necesito|quiero|dame|j ai besoin|je voudrais|je veux|donne moi|ich brauche|ich will|gib mir|"
    r"preciso de|quero|ho bisogno di|voglio"
)
# Infinitives of the make verbs, for "quiero hacer una presentacion".
_MAKE_INFINITIVES = frozenset((
    "hacer crear generar preparar escribir redactar disenar faire creer generer ecrire rediger erstellen machen "
    "schreiben generieren fazer criar gerar escrever preparar fare creare generare scrivere maken schrijven "
    "genereren").split())
_DETERMINERS = frozenset((
    "un una unos unas el la los las le les l d des du de eine einen einem ein um uma uns umas o a os as uno gli "
    "een het mi mis mon ma mes mein meine meinen meinem mijn meu minha mio mia").split())
_LEAD_MAKE = re.compile(rf"^(?:\W*)(?:{_POLITE})(?:{_MAKE_VERBS})\b")
_LEAD_WANT = re.compile(rf"^(?:\W*)(?:{_POLITE})(?:{_WANT_VERBS})\b")
_NOUNS = (
    ("deck", r"presentations?|presentacion(?:es)?|diapositivas?|powerpoints?|pptx?|diaporamas?|slideshows?|slides?|praesentation|"
             r"prasentation|folien|apresentacao|apresentacoes|presentazione|presentatie|keynote|deck"),
    ("sheet", r"hojas? de calculo|tableur|tabellenkalkulation|planilha|foglio di calcolo|excel|xlsx|spreadsheets?|csv"),
    ("doc", r"informes?|reporte|curriculum|curriculo|documento|rapport|cv|bericht|lebenslauf|dokument|relatorio|docx"),
    ("pdf", r"pdfs?"),
)
_NOUN_RE = [(kind, re.compile(rf"\b(?:{words})\b")) for kind, words in _NOUNS]
# A request for software that happens to mention a document is not a request for one.
_FOREIGN_CODE = re.compile(r"\b(?:script|scripts|skript|codigo|code|funcion|fonction|funktion|funzione|programa|"
                           r"programme|programm|app|api|bot|parser|bibliotheca|libreria|biblioteca)\b")
# Only these may sit between the request verb and the format noun: the noun has to be the direct
# object. Anything else ("hazme una pregunta sobre el pdf", "fais un resume de ce pdf") means the
# file is a topic or an existing thing, and a demonstrative ("este", "ce", "das") points at one.
_PRONOUNS = frozenset("me mi mir mich moi nos uns te toi lhe".split())
_ADJECTIVES = frozenset((
    "nueva nuevo breve corta corto buena buen pequena pequeno nouveau nouvelle court courte bon bonne "
    "neue neuen neues neuer kurze kurzen kurzes gute guten gutes nova novo curta curto boa bom nuova nuovo "
    "buona nieuwe nieuw korte goed kleine simple simples rapido rapida rapide schnelle").split())

_ZH_NOUN = r"(幻灯片|演示文稿|演示|ppt|pptx|pdf|excel|电子表格|表格|工作表|报告|简历|文档)"
_ZH_VERB = r"(?:做|写|制作|生成|创建|设计|编写|来个|整个|搞个|弄个|出个)"
# A request: a make verb opens the clause ("做个ppt"), or a marker such as 帮我/给我/请/我要 comes first and
# the make verb follows it directly. A verb in the middle of a statement ("我在写报告", "我昨天做了一个ppt")
# is not a request, and neither is a marker with some other verb ("帮我总结这份报告", "请把这个pdf翻译成中文").
# Only a measure word and a short qualifier ending in 的 may sit between the verb and the noun.
_ZH_ASK = re.compile(rf"(?:^\W*|(?:帮我|给我|请|麻烦|我要|我想要?|我需要)){_ZH_VERB}"
                     rf"(?:一个|一份|一篇|个|份|篇)?((?:关于[^，。,.？?]{{1,12}}?的|[^，。,.？?]{{0,6}}?的)?){_ZH_NOUN}")
_ZH_NOT = re.compile(r"怎么|如何|怎样|什么|吗|是否|代码|脚本|程序|函数|解析|在|了|不会|昨天|正在|已经|没|过")
# What the qualifier says about an existing file rather than a new one.
_ZH_EXISTING = re.compile(r"把|这个|这份|这张|那个|那份|总结|翻译|打开|解释|检查|学习|提问")
_ZH_KIND = {"幻灯片": "deck", "演示文稿": "deck", "演示": "deck", "ppt": "deck", "pptx": "deck", "pdf": "pdf",
            "excel": "sheet", "电子表格": "sheet", "表格": "sheet", "工作表": "sheet",
            "报告": "doc", "简历": "doc", "文档": "doc"}


def _find_noun(rest: str) -> Optional[tuple[int, str]]:
    found: Optional[tuple[int, str]] = None
    for kind, pattern in _NOUN_RE:
        m = pattern.search(rest)
        if m and (found is None or m.start() < found[0]):
            found = (m.start(), kind)
    return found


def foreign_hit(clause: str) -> Optional[tuple[str, bool]]:
    """(kind, strong) when the clause is a non-English request to make a file, else None."""
    if not clause or "?" in clause or "¿" in clause:
        return None
    zh = _ZH_ASK.search(clause.lower())
    if zh and not _ZH_NOT.search(clause) and not _ZH_EXISTING.search(zh.group(1)):
        kind = _ZH_KIND[zh.group(2)]
        return kind, kind != "doc"
    folded = _fold(clause).strip()
    make = _LEAD_MAKE.match(folded)
    want = None if make else _LEAD_WANT.match(folded)
    lead = make or want
    if not lead:
        return None
    rest = folded[lead.end():].strip()
    if want:
        # Only the thing itself ("necesito una presentacion") or a make verb ("quiero hacer un informe");
        # "quiero abrir un pdf" and "necesito ayuda con mi presentacion" want something else.
        words = rest.split()
        while words and words[0] in _DETERMINERS and len(words) > 1:
            words = words[1:]
        if words and words[0] in _MAKE_INFINITIVES:
            rest = " ".join(words[1:])
        else:
            rest = " ".join(words)
            nm = next((p.match(rest) for _, p in _NOUN_RE if p.match(rest)), None)
            if not nm:
                return None
    found = _find_noun(rest)
    if not found:
        return None
    between = rest[:found[0]].split()
    if any(not (w in _DETERMINERS or w in _PRONOUNS or w in _ADJECTIVES or w.isdigit()) for w in between):
        return None
    after = re.findall(r"[a-z0-9]+", rest[found[0]:])[:6]
    if any(_FOREIGN_CODE.fullmatch(w) for w in after[1:]):
        return None
    return found[1], found[1] != "doc"
