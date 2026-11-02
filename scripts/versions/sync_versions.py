"""Stamp the root VERSION into every place that ships a Harvis version, or check them.

    python3 scripts/versions/sync_versions.py           # write
    python3 scripts/versions/sync_versions.py --check   # exit 1 on drift (CI)

Two strings are deliberately NOT Harvis's version and are left alone: the Hermes UI
package.json (it tracks the upstream desktop app it was forked from) and the facade's
"0.21.0-harvis-facade" (the Hermes gateway protocol the UI was written against).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# path -> (pattern whose group 1 is the version, how to write it back)
TARGETS = {
    "python_back_end/VERSION": (re.compile(r"\A(.*)\n?\Z"), lambda v: f"{v}\n"),
    "harvis-helm-chart/Chart.yaml": (re.compile(r'^appVersion: "([^"]*)"$', re.M), lambda v: f'appVersion: "{v}"'),
}


def main(check: bool) -> int:
    version = (ROOT / "VERSION").read_text().strip()
    if not SEMVER.match(version):
        print(f"VERSION is not x.y.z: {version!r}")
        return 1
    drift = []
    for rel, (pattern, render) in TARGETS.items():
        path = ROOT / rel
        text = path.read_text()
        found = pattern.search(text)
        if not found:
            print(f"{rel}: no version found")
            return 1
        if found.group(1) == version:
            continue
        drift.append(f"{rel}: {found.group(1)} (want {version})")
        if not check:
            path.write_text(text[: found.start()] + render(version) + text[found.end():])
    for line in drift:
        print(line)
    if check and drift:
        print("Run: python3 scripts/versions/sync_versions.py")
        return 1
    print(f"Harvis {version}: {'in sync' if not drift else f'stamped {len(drift)} file(s)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))
