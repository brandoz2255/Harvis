"""
creator — scaffolding + verification helper for files the agent writes.

Same chokepoint pattern as the other skills:
  • Every file the agent creates can flow through `creator.py write` to get
    auto-verified (syntax check by extension) before being reported as done.
  • Templates for common scaffolds (python-cli, bash, dockerfile, flask,
    fastapi, github-action, gitignore-python) live in templates/ next to
    this script — drop new ones in there and they're auto-discovered.

Subcommands:
    scaffold <template> --out PATH [--vars k=v k=v ...]
    write    <path>     [--content STR | --stdin]
    verify   <path>
    list-templates

Returns JSON on every command so the agent can parse the result without
guessing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------- verification ----------

def verify_python(path: Path) -> tuple[bool, list[str]]:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if r.returncode == 0:
            return True, []
        return False, [r.stderr.strip() or "py_compile failed"]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, [str(exc)[:200]]


def verify_json(path: Path) -> tuple[bool, list[str]]:
    try:
        with open(path) as f:
            json.load(f)
        return True, []
    except (json.JSONDecodeError, OSError) as exc:
        return False, [str(exc)[:200]]


def verify_bash(path: Path) -> tuple[bool, list[str]]:
    try:
        r = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if r.returncode == 0:
            return True, []
        return False, [r.stderr.strip() or "bash -n failed"]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, [str(exc)[:200]]


def verify_yaml(path: Path) -> tuple[bool, list[str]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return True, ["(yaml module unavailable — syntax not verified)"]
    try:
        with open(path) as f:
            yaml.safe_load(f)
        return True, []
    except (yaml.YAMLError, OSError) as exc:
        return False, [str(exc)[:200]]


def verify_file(path: Path) -> dict:
    """Verify a file by extension. Returns {syntax_ok, errors, kind}."""
    if not path.exists():
        return {"syntax_ok": False, "errors": ["file does not exist"], "kind": "missing"}
    if not path.is_file():
        return {"syntax_ok": False, "errors": ["not a regular file"], "kind": "not-a-file"}

    ext = path.suffix.lower()
    if ext == ".py":
        ok, errs = verify_python(path)
        kind = "python"
    elif ext == ".json":
        ok, errs = verify_json(path)
        kind = "json"
    elif ext == ".sh" or ext == ".bash":
        ok, errs = verify_bash(path)
        kind = "bash"
    elif ext in (".yaml", ".yml"):
        ok, errs = verify_yaml(path)
        kind = "yaml"
    else:
        # Best-effort: file readable, no obvious binary garbage
        try:
            data = path.read_bytes()
            null_count = data.count(b"\x00")
            ok = null_count == 0 or ext in (".bin", ".png", ".jpg", ".pdf", ".zip", ".tar", ".gz")
            errs = ([] if ok else
                    [f"contains {null_count} null bytes — looks binary not text"])
            kind = ext.lstrip(".") or "text"
        except OSError as exc:
            ok, errs, kind = False, [str(exc)[:200]], "unreadable"
    return {"syntax_ok": ok, "errors": errs, "kind": kind}


# ---------- templates ----------

def list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.iterdir() if p.is_file())


def render_template(name: str, vars: dict) -> str:
    p = TEMPLATES_DIR / name
    if not p.exists():
        # Try common extensions in case the user supplied bare name
        for ext in (".py", ".sh", ".dockerfile", ".yml", ".yaml", ".tmpl", ""):
            cand = TEMPLATES_DIR / f"{name}{ext}"
            if cand.exists():
                p = cand
                break
        else:
            raise FileNotFoundError(f"template not found: {name}")
    text = p.read_text()
    # Simple {{ var }} substitution — no jinja dependency
    for k, v in vars.items():
        text = text.replace(f"{{{{ {k} }}}}", str(v))
        text = text.replace(f"{{{{{k}}}}}", str(v))
    return text


# ---------- write ----------

def write_file(path: Path, content: str) -> dict:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    bytes_written = len(content.encode("utf-8"))
    info = verify_file(path)
    return {
        "path": str(path),
        "bytes": bytes_written,
        "lines": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
        **info,
    }


# ---------- CLI ----------

def cmd_scaffold(args) -> int:
    vars_dict: dict = {}
    for kv in args.vars or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            vars_dict[k.strip()] = v
    try:
        content = render_template(args.template, vars_dict)
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc), "available": list_templates()}, indent=2))
        return 1
    out = Path(args.out).expanduser()
    result = write_file(out, content)
    result["template"] = args.template
    result["vars"] = vars_dict
    print(json.dumps(result, indent=2))
    return 0 if result["syntax_ok"] else 2


def cmd_write(args) -> int:
    if args.stdin:
        content = sys.stdin.read()
    elif args.content is not None:
        content = args.content
    else:
        print(json.dumps({"error": "supply --content STR or --stdin"}))
        return 1
    out = Path(args.path).expanduser()
    result = write_file(out, content)
    print(json.dumps(result, indent=2))
    return 0 if result["syntax_ok"] else 2


def cmd_verify(args) -> int:
    info = verify_file(Path(args.path).expanduser())
    info["path"] = str(Path(args.path).expanduser())
    print(json.dumps(info, indent=2))
    return 0 if info["syntax_ok"] else 1


def cmd_list(args) -> int:
    print(json.dumps({"templates": list_templates(),
                      "templates_dir": str(TEMPLATES_DIR)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold + write + verify helper")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s_scaffold = sp.add_parser("scaffold", help="render a template to a path")
    s_scaffold.add_argument("template", help="template name (see list-templates)")
    s_scaffold.add_argument("--out", required=True, help="output path")
    s_scaffold.add_argument("--vars", nargs="*", default=[],
                            help="key=value substitutions for the template")
    s_scaffold.set_defaults(fn=cmd_scaffold)

    s_write = sp.add_parser("write", help="write content to a path + verify")
    s_write.add_argument("path", help="output path")
    s_write.add_argument("--content", help="content as a string")
    s_write.add_argument("--stdin", action="store_true",
                         help="read content from stdin")
    s_write.set_defaults(fn=cmd_write)

    s_verify = sp.add_parser("verify", help="syntax-verify an existing file")
    s_verify.add_argument("path")
    s_verify.set_defaults(fn=cmd_verify)

    s_list = sp.add_parser("list-templates", help="list available templates")
    s_list.set_defaults(fn=cmd_list)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
