"""The agent loop must not ship an announcement as the deliverable.

A model that says what it is about to do and then calls no tool has stalled,
not finished. `_is_narration` is what tells the two apart so the loop can ask
for the call instead of ending the run on "Let me take a fresh snapshot".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration.runner import _is_narration  # noqa: E402


def test_announcement_of_a_next_action_is_narration():
    assert _is_narration("Let me take a fresh snapshot to see the current state of the page.")
    assert _is_narration("I'll open the search results now.")
    assert _is_narration("Now I'm going to click the first link.")
    assert _is_narration("Okay, let's scroll down.")
    assert _is_narration("Next, I will read the second result.")


def test_an_actual_answer_is_not_narration():
    assert not _is_narration(
        "The top three cat breeds on the page are Maine Coon, Ragdoll, and Siamese."
    )
    assert not _is_narration("Done. The file now imports cleanly.")


def test_empty_and_whitespace_are_not_narration():
    assert not _is_narration("")
    assert not _is_narration("   \n  ")
    assert not _is_narration(None)


def test_a_long_answer_that_merely_opens_with_let_me_is_kept():
    # "Let me walk you through it" followed by the actual walk-through is a
    # deliverable; discarding it would lose the answer the run was asked for.
    body = "Let me walk you through what I found. " + ("The page lists ten breeds. " * 20)
    assert not _is_narration(body)


def test_multi_paragraph_content_is_kept():
    assert not _is_narration("Let me summarize.\n\nOne.\n\nTwo.\n\nThree.")


def test_decoration_around_the_announcement_still_counts():
    assert _is_narration('"Let me check the page."')
    assert _is_narration("- Let me scroll down further.")
    assert _is_narration("**I'll try the next link.**")


def test_nudge_budget_is_configurable_and_bounded():
    from workspace.orchestration import runner

    assert runner._MAX_STALL_RETRIES >= 0
    # A spent budget must fall through to the answer round rather than loop.
    assert runner._MAX_STALL_RETRIES <= 5
