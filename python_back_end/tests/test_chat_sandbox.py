"""Persistent Claude chat sandbox + live markdown mapping.

The subscription chat used to dump `--output-format text` in one blob, refuse Bash,
and write into a per-run /tmp dir — so the model could not keep notes, run Python,
or show a script as it was typed.
"""

import unittest

from owui_compat.chat_files import chat_workdir
from owui_compat.cloud_chat import (
    _CHAT_SANDBOX_SYSTEM,
    _cli_visible_delta,
    _format_write_markdown,
)


class TestChatWorkdir(unittest.TestCase):
    def test_persistent_per_user_not_per_run(self):
        a = chat_workdir(7, "run-aaaa")
        b = chat_workdir(7, "run-bbbb")
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("/u7"))
        self.assertNotIn("run-aaaa", a)
        self.assertTrue(a.startswith("/data/artifacts/harvis-chat"))

    def test_users_are_isolated(self):
        self.assertNotEqual(chat_workdir(1), chat_workdir(2))


class TestSandboxPrompt(unittest.TestCase):
    def test_tells_the_model_it_can_write_and_run(self):
        p = _CHAT_SANDBOX_SYSTEM
        self.assertIn("notes.md", p)
        self.assertIn("python3", p)
        self.assertIn("harvis-check.sh", p)
        self.assertIn("Markdown", p)
        self.assertIn("PERSIST", p.upper())


class TestLiveMarkdown(unittest.TestCase):
    def test_write_becomes_a_fenced_block(self):
        md = _format_write_markdown({
            "file_path": "/data/artifacts/harvis-chat/u1/hello.py",
            "content": "print('hi')\n",
        })
        self.assertIn("```python", md)
        self.assertIn("print('hi')", md)
        self.assertIn("hello.py", md)

    def test_assistant_text_passes_through(self):
        obj = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "## Hello\n\nworld"}]},
        }
        self.assertEqual(_cli_visible_delta(obj), "## Hello\n\nworld")

    def test_write_tool_use_is_visible(self):
        obj = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "name": "Write",
                "input": {"file_path": "app.js", "content": "console.log(1)"},
            }]},
        }
        out = _cli_visible_delta(obj)
        self.assertIn("```javascript", out)
        self.assertIn("console.log(1)", out)

    def test_result_line_is_not_dumped(self):
        obj = {"type": "result", "subtype": "success", "result": "the whole answer again"}
        self.assertEqual(_cli_visible_delta(obj), "")


if __name__ == "__main__":
    unittest.main()
