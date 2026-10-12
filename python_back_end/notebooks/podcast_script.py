"""Write a podcast script that is the length asked for and keeps its speakers straight.

The old one-shot prompt asked a small model for "about N exchanges" in a single
reply, so a 10 minute request came back as 30 seconds of talk; it let the model
invent speaker labels ("Host", "Speaker 1", "Alex:") that the voice step then
treated as different people; and when the reply was not valid JSON it saved the
first 500 characters of raw text as a finished podcast.

Here the script is written in parts sized from the request (150 spoken words per
minute), each part is told where the last one stopped, every line is mapped onto
the speaker names that were asked for, and anything that cannot be read as a
script raises PodcastScriptError with a message the user can act on.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE = 150
PART_WORDS = 600
MAX_PARTS = 8
MIN_MINUTES, MAX_MINUTES = 1, 30
MAX_SPEAKERS = 4  # the speech service ships four voices
SOURCE_CHARS = 18000
DEFAULT_NAMES = ("Alex", "Sam", "Jordan", "Riley")
CALL_TIMEOUT_S = float(os.getenv("NOTEBOOK_PODCAST_CALL_TIMEOUT", "300"))

STYLE_NOTES = {
    "conversational": "a relaxed back-and-forth between friends who find the topic interesting",
    "interview": "an interview: the first speaker asks questions, the others answer in depth",
    "educational": "a clear teaching episode that explains ideas step by step with examples",
    "debate": "a friendly debate where the speakers take different sides and respond to each other",
    "storytelling": "a narrative that weaves the material into a story",
}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "outline": {"type": "string"},
        "transcript": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"speaker": {"type": "string"}, "dialogue": {"type": "string"}},
                "required": ["speaker", "dialogue"],
            },
        },
    },
    "required": ["transcript"],
}


class PodcastScriptError(Exception):
    """The script could not be written. ``str(exc)`` is shown to the user."""


Caller = Callable[[str, int], Awaitable[str]]


def clamp_minutes(minutes: Optional[int]) -> int:
    try:
        value = int(minutes or 0)
    except (TypeError, ValueError):
        value = 0
    return max(MIN_MINUTES, min(MAX_MINUTES, value or 5))


def speaker_names(custom: Optional[Sequence[Dict[str, Any]]], count: Optional[int]) -> List[str]:
    """The cast: custom speaker names when given, else friendly defaults. 1 to 4 of them."""
    names: List[str] = []
    for item in custom or []:
        name = " ".join(str((item or {}).get("name") or "").split())
        if name and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    wanted = count or len(names) or 2
    wanted = max(1, min(MAX_SPEAKERS, wanted))
    for default in DEFAULT_NAMES:
        if len(names) >= wanted:
            break
        if default.casefold() not in {n.casefold() for n in names}:
            names.append(default)
    return names[:wanted]


def target_words(minutes: int) -> int:
    return clamp_minutes(minutes) * WORDS_PER_MINUTE


def plan_parts(total_words: int) -> List[int]:
    """Words to ask for in each part. Short episodes are one part."""
    n = max(1, min(MAX_PARTS, math.ceil(total_words / PART_WORDS)))
    base, extra = divmod(total_words, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def word_count(turns: Sequence[Dict[str, str]]) -> int:
    return sum(len(t["dialogue"].split()) for t in turns)


_STAGE = re.compile(r"\[[^\]]{0,60}\]|\*[^*\n]{1,40}\*")
_LABEL_NOISE = re.compile(r"[\*_`#]+|\([^)]*\)|\[[^\]]*\]")
_ROLE_INDEX = re.compile(r"^(?:speaker|host|guest|voice|person|s|h|participant)\s*#?\s*(\d+)$")


def _clean_label(raw: Any) -> str:
    label = _LABEL_NOISE.sub(" ", str(raw or ""))
    return " ".join(label.replace(":", " ").split())


def clean_dialogue(raw: Any, labels: Sequence[str] = ()) -> str:
    text = str(raw or "").strip()
    # A model often repeats the label inside the line ("Alex: Welcome...").
    for label in labels:
        text = re.sub(rf"^\s*\**{re.escape(label)}\**\s*:\s*", "", text, flags=re.IGNORECASE)
    text = _STAGE.sub(" ", text)
    text = text.replace("*", "")
    return " ".join(text.split())


def normalize_turns(turns: Sequence[Dict[str, Any]], names: Sequence[str]) -> List[Dict[str, str]]:
    """Map every line onto one of ``names`` and drop empty lines.

    Matches by exact name, first name, "Speaker 2"/"Host"/"Guest" style labels, then
    hands unknown labels the next unused name; when everyone is taken they take turns,
    never the person who just spoke. So the audio step sees at most len(names) people.
    """
    canon = {n.casefold(): n for n in names}
    seen: Dict[str, str] = {}
    out: List[Dict[str, str]] = []
    last = ""

    def resolve(label: str) -> str:
        key = label.casefold()
        if key in canon:
            return canon[key]
        if key in seen:
            return seen[key]
        match = _ROLE_INDEX.match(key)
        if match and 1 <= int(match.group(1)) <= len(names):
            return names[int(match.group(1)) - 1]
        if key in ("host", "interviewer", "moderator", "narrator"):
            return names[0]
        if key in ("guest", "expert", "co-host", "cohost") and len(names) > 1:
            return names[1]
        words = key.split()
        for n in names:
            first = n.casefold().split()[0]
            if words and (words[0] == first or first in words):
                return n
        unused = [n for n in names if n not in seen.values()]
        if unused:
            return unused[0]
        others = [n for n in names if n != last] or list(names)
        return others[len(seen) % len(others)]

    for turn in turns:
        label = _clean_label(turn.get("speaker") or turn.get("name") or turn.get("role"))
        text = clean_dialogue(turn.get("dialogue") or turn.get("text") or turn.get("line") or turn.get("content"), [label] if label else [])
        if not text:
            continue
        who = resolve(label or "speaker")
        seen[(label or "speaker").casefold()] = who
        out.append({"speaker": who, "dialogue": text})
        last = who
    return out


def parse_turns(raw: str) -> Tuple[str, List[Dict[str, Any]]]:
    """``(outline, turns)`` from a model reply, or raise PodcastScriptError."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    if not text:
        raise PodcastScriptError("The model returned nothing. Try again, or pick a different model.")
    candidates = [text]
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])
    first, last = text.find("["), text.rfind("]")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            data = {"transcript": data}
        if isinstance(data, dict):
            turns = data.get("transcript") or data.get("dialogue") or data.get("script") or data.get("turns")
            if isinstance(turns, list) and all(isinstance(t, dict) for t in turns) and turns:
                return str(data.get("outline") or ""), turns
    raise PodcastScriptError(
        "The model did not return a script Notebooks could read (it answered in a format that is not JSON). "
        "Try again, or pick a larger model for audio overviews."
    )


def _chunks_of(content: str, parts: int) -> List[str]:
    content = content.strip()[:SOURCE_CHARS]
    if parts <= 1:
        return [content]
    size = math.ceil(len(content) / parts)
    return [content[i * size : (i + 1) * size] or content[-size:] for i in range(parts)]


def build_prompt(
    *, title: str, style: str, names: Sequence[str], part: int, parts: int, words: int, material: str, previous: Sequence[Dict[str, str]]
) -> str:
    feel = STYLE_NOTES.get(style, STYLE_NOTES["conversational"])
    cast = ", ".join(names)
    if len(names) == 1:
        cast_line = f"There is one speaker, {names[0]}, giving a spoken monologue."
    else:
        cast_line = f"The speakers are {cast}. Use exactly these names in the speaker field, nothing else."
    if part == 1:
        position = "This is the opening: greet the listener and say what the episode covers." if parts > 1 else (
            "This is the whole episode: open by greeting the listener, then cover the material, then close."
        )
    elif part == parts:
        position = "This is the final part: finish the discussion, summarise the key takeaways and say goodbye."
    else:
        position = f"This is part {part} of {parts}. Do not greet and do not wrap up; keep going into new material."
    recap = ""
    if previous:
        tail = "\n".join(f"{t['speaker']}: {t['dialogue']}" for t in previous[-3:])
        recap = f"\nThe script so far ends with:\n{tail}\nContinue directly from there without repeating it.\n"
    return (
        f'You write scripts for an audio podcast titled "{title}". Style: {feel}.\n{cast_line}\n'
        f"{position}{recap}\n"
        f"Write about {words} spoken words for this part (about {max(2, round(words / 35))} to "
        f"{max(4, round(words / 20))} turns). Plain spoken sentences only: no stage directions, no sound effects, "
        "no markdown, no emoji, no speaker names inside the dialogue text. Use ONLY facts from the material below.\n\n"
        f"MATERIAL:\n---\n{material}\n---\n\n"
        'Reply with JSON only: {"outline": "one line on what this part covers", '
        '"transcript": [{"speaker": "<name>", "dialogue": "<what they say>"}]}'
    )


def ollama_caller(model: str, ollama_url: str) -> Caller:
    """Ask Ollama for JSON. Falls back to free-form output on a server that rejects ``format``."""

    async def call(prompt: str, num_predict: int) -> str:
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": SCRIPT_SCHEMA,
            "options": {"temperature": 0.7, "num_predict": num_predict},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(CALL_TIMEOUT_S)) as client:
                resp = await client.post(f"{ollama_url}/api/generate", json=body)
                if resp.status_code == 400:
                    body.pop("format")
                    resp = await client.post(f"{ollama_url}/api/generate", json=body)
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.TimeoutException as exc:
            raise PodcastScriptError("The model took too long to write the script. Try a shorter length or a faster model.") from exc
        except httpx.HTTPStatusError as exc:
            raise PodcastScriptError(
                f"The model server answered HTTP {exc.response.status_code} for model {model}. "
                "Check that the model is installed."
            ) from exc
        except httpx.HTTPError as exc:
            raise PodcastScriptError(f"The model server could not be reached ({type(exc).__name__}).") from exc

    return call


async def generate_script(
    content: str,
    *,
    title: str,
    style: str,
    minutes: int,
    names: Sequence[str],
    call: Caller,
) -> Dict[str, Any]:
    """Write the whole script. Returns ``{outline, transcript, words, target_words}``."""
    goal = target_words(minutes)
    plan = plan_parts(goal)
    material = _chunks_of(content, len(plan))
    turns: List[Dict[str, str]] = []
    outlines: List[str] = []
    owed = 0
    for i, words in enumerate(plan, 1):
        ask = max(80, words + owed)
        prompt = build_prompt(
            title=title, style=style, names=names, part=i, parts=len(plan), words=ask, material=material[i - 1], previous=turns
        )
        budget = min(8192, int(ask * 2.6) + 300)
        part_turns: List[Dict[str, str]] = []
        for attempt in (1, 2):
            try:
                outline, raw_turns = parse_turns(await call(prompt, budget))
                part_turns = normalize_turns(raw_turns, names)
                if part_turns:
                    if outline:
                        outlines.append(outline)
                    break
            except PodcastScriptError:
                if attempt == 2:
                    raise
            logger.info("podcast part %s/%s attempt %s gave no usable script, retrying", i, len(plan), attempt)
        if not part_turns:
            raise PodcastScriptError("The model's script had no spoken lines. Try again, or pick a different model.")
        turns.extend(part_turns)
        owed = max(0, goal * i // len(plan) - word_count(turns))
        owed = min(owed, words)  # catch up, but never ask for more than double a part
    return {
        "outline": " ".join(outlines) if outlines else f"Audio overview: {title}",
        "transcript": turns,
        "words": word_count(turns),
        "target_words": goal,
    }
