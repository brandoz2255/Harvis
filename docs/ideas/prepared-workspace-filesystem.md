# Idea: start the agent in a prepared filesystem, not an empty one

**Status:** idea only. Nothing built. Source details still outstanding — see "What's missing".
**Raised:** 2026-08-25

## The idea

Today every agent lane in Harvis starts from something close to nothing. A workspace run gets a
fresh sandbox, a vibecode session gets whatever folder the user linked (often none), and a plain
chat gets no filesystem at all. The model has to discover its surroundings on every single run,
and it has nowhere to leave anything behind.

The ask is to do what the Grok bot does: **start the AI inside a set filesystem** — a known,
prepared working directory that is the same every time — so it performs better. Instead of "here
is an empty box, figure it out", the agent opens into a layout it already understands.

Roughly, the prepared root would carry:

- A stable place to work, at a stable path, so instructions can name real directories.
- Seeded material the agent is expected to use — skills, reference docs, project notes, templates.
- Scratch space that persists across runs within a session, so step two can build on step one.
- An orientation file at the root that describes the layout, so the model reads one file instead
  of probing with `ls` for its first four tool calls.

## Why it should help

- **Fewer wasted turns.** A large share of early tool calls in a run are the model orienting
  itself. A known layout plus one orientation file removes most of that.
- **Instructions can be concrete.** "Put the report in `output/`" is a usable instruction only if
  `output/` reliably exists.
- **Continuity.** Work survives between steps and between runs instead of dying with the sandbox.
- **Skills become reachable as files.** Harvis already has a skills directory concept; a prepared
  root is the natural place to mount it so the agent can actually read a skill rather than being
  told about one.

## Where it would attach in Harvis

These are the existing pieces this would touch — none of it is designed yet:

- The sandbox/workspace runner, which currently provisions the per-run container filesystem.
- The engine sidecars (openclaw, codex, claude-code, hermes-agent), which already receive a shared
  skills mount via `docker-compose.yaml`.
- Vibecode sessions, which already have a `local_folder` concept — the closest existing analogue.

## Open questions

- Is the prepared root **per user**, **per session**, or **per project**? Each has a different
  persistence and isolation story.
- What survives a run, and what gets wiped? A root that accumulates junk forever gets worse, not
  better.
- How does this interact with the security posture — the model must still never receive host
  paths, storage keys, or anything outside its own root.
- Does the orientation file get authored by Harvis, by the user, or both?

## What's missing

The person who raised this has the reference material for how the Grok bot does it **on
Instagram**, and it has not been supplied yet. This note captures the described intent only. Before
designing anything, get that material — the specifics of the layout are the whole point, and
guessing at them would produce a different feature that happens to share a name.
