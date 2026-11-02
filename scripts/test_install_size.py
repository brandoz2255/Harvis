"""Tests for install-size.py and the ledger line verify-fresh-install.sh appends. Docker is a
fake program on PATH serving canned answers and logging what it was asked: the estimator must
only ever read."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ESTIMATOR = os.path.join(HERE, "install-size.py")
VERIFY = os.path.join(HERE, "verify-fresh-install.sh")

spec = importlib.util.spec_from_file_location("install_size", ESTIMATOR)
install_size = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_size)

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
fx = json.load(open(os.environ["FAKE_DOCKER_FIXTURE"]))
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[:1] == ["info"]:
    print(json.dumps([["driver-type", "io.containerd.snapshotter.v1"]]))
elif a[:1] == ["version"]:
    print("99.0.0")
elif a[:2] == ["compose", "version"]:
    print("9.9.9")
elif a[:1] == ["compose"] and "config" in a:
    if "--services" in a:
        print("\n".join(fx["compose"]["services"]))
    else:
        print(json.dumps(fx["compose"]))
elif a[:1] == ["compose"]:
    pass
elif a[:2] == ["image", "inspect"]:
    img = fx["images"].get(a[2]) or next((i for i in fx["images"].values() if i["Id"] == a[2]), None)
    if img is None:
        sys.exit("Error: No such image: " + a[2])
    print(json.dumps([{"Id": img["Id"], "Size": img["Size"], "Created": "2026-01-01T00:00:00Z",
                       "RootFS": {"Layers": [l for l, _ in img["layers"]]}}]))
elif a[:1] == ["history"]:
    img = next(i for i in fx["images"].values() if i["Id"] == a[-1])
    print("\n".join(str(s) for _, s in reversed(img["layers"])) + "\n0")
elif a[:2] == ["images", "-q"]:
    print("\n".join(sorted({i["Id"][:12] for i in fx["images"].values()})))
elif a[:1] == ["images"]:
    pass
elif a[:2] == ["system", "df"] and "-v" in a:
    print(json.dumps({"Images": fx["df_images"]}))
elif a[:2] == ["system", "df"]:
    print("\n".join(json.dumps(r) for r in fx["df"]))
else:
    sys.exit("fake docker: unexpected " + " ".join(a))
'''

FAKE_CURL = "#!/bin/sh\nexit 22\n"

MB = 1_000_000
# base shares layer L1 with both app images; app-b also has a layer of its own.
FIXTURE = {
    "images": {
        "base:1": {"Id": "sha256:" + "b" * 64, "Size": 150 * MB, "layers": [("L1", 100 * MB)]},
        "app-a:1": {"Id": "sha256:" + "a" * 64, "Size": 300 * MB, "layers": [("L1", 100 * MB), ("L2", 100 * MB)]},
        "harvis-b": {"Id": "sha256:" + "c" * 64, "Size": 450 * MB, "layers": [("L1", 100 * MB), ("L3", 200 * MB)]},
    },
    "compose": {"name": "harvis", "services": {
        "a": {"image": "app-a:1"},
        "b": {"build": {"context": "@CONTEXT@", "dockerfile": "Dockerfile"}},
        "c": {"image": "not-here:1", "profiles": ["opt"]},
    }},
    "df": [{"Type": "Images", "Size": "0.6GB", "TotalCount": "3"}, {"Type": "Local Volumes", "Size": "10MB"},
           {"Type": "Build Cache", "Size": "1.5GB"}, {"Type": "Containers", "Size": "1MB"}],
    "df_images": [{"Repository": "app-a", "Tag": "1", "ID": "sha256:" + "a" * 64, "Size": "300MB", "UniqueSize": "N/A"}],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "docker.log")
        context = os.path.join(self.tmp, "ctx")
        os.makedirs(context)
        with open(os.path.join(context, "Dockerfile"), "w") as fh:
            fh.write("FROM base:1\nRUN true\n")
        fixture = json.loads(json.dumps(FIXTURE).replace("@CONTEXT@", context))
        self.fixture = os.path.join(self.tmp, "fixture.json")
        with open(self.fixture, "w") as fh:
            json.dump(fixture, fh)
        self.fake("docker", FAKE_DOCKER)
        self.fake("curl", FAKE_CURL)
        self.history = os.path.join(self.tmp, "state", "history.jsonl")

    def fake(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)

    def env(self, **extra):
        return {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": self.tmp, "FAKE_DOCKER_FIXTURE": self.fixture,
                "FAKE_DOCKER_LOG": self.log, "INSTALL_SIZE_HISTORY": self.history, **extra}

    def docker_calls(self):
        with open(self.log) as fh:
            return fh.read().splitlines()


class EstimatorTest(Base):
    def run_estimator(self, *args):
        compose = os.path.join(self.tmp, "docker-compose.yaml")
        open(compose, "w").close()
        proc = subprocess.run([sys.executable, ESTIMATOR, "-f", compose, "--json", *args],
                              capture_output=True, text=True, env=self.env(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_a_shared_layer_is_counted_once(self):
        default = self.run_estimator()["default"]
        by_ref = {r["ref"]: r for r in default["images"]}
        # a comes first and pays for L1+L2; b's build base is all L1, so it adds nothing; b adds only L3.
        self.assertEqual(by_ref["base:1"]["status"], "known")
        self.assertEqual(by_ref["app-a:1"]["new_layers"], 2)
        self.assertEqual(by_ref["base:1"]["new_layers"], 0)
        self.assertEqual(by_ref["harvis-b"]["new_layers"], 1)
        # unpacked: L1 + L2 + L3 = 400 MB once; naive sum of sizes counts L1 three times.
        self.assertEqual(default["unpacked_bytes"], 400 * MB)
        self.assertEqual(default["naive_sum_bytes"], 900 * MB)
        # compressed blobs: a has 100 MB over 200 MB unpacked, b has 150 MB over 300 MB.
        self.assertEqual(default["footprint_bytes"], default["unpacked_bytes"] + default["content_bytes"])
        self.assertGreater(default["content_bytes"], 0)

    def test_an_image_missing_from_the_store_is_unknown_not_guessed(self):
        result = self.run_estimator("--profile", "opt")
        self.assertEqual(result["default"]["unknown"], [])
        self.assertEqual(result["selected"]["unknown"], ["not-here:1"])
        self.assertTrue(result["lower_bound"])
        self.assertEqual(result["selected"]["footprint_bytes"], result["default"]["footprint_bytes"])

    def test_each_profile_reports_only_what_it_adds(self):
        result = self.run_estimator("--each-profile")
        self.assertEqual(result["per_profile"]["opt"]["added_bytes"], 0)
        self.assertEqual(result["per_profile"]["opt"]["unknown"], ["not-here:1"])

    def test_it_only_reads_docker(self):
        self.run_estimator("--each-profile")
        calls = self.docker_calls()
        self.assertTrue(calls)
        for call in calls:
            self.assertRegex(call, r"^(info |version |compose --env-file /dev/null .* config |image inspect |history )", call)

    def test_a_required_compose_variable_gets_a_placeholder_instead_of_failing(self):
        self.fake("docker", FAKE_DOCKER.replace(
            'elif a[:1] == ["compose"] and "config" in a:',
            'elif a[:1] == ["compose"] and "config" in a and "JWT_SECRET" not in os.environ:\n'
            '    sys.exit("required variable JWT_SECRET is missing a value")\n'
            'elif a[:1] == ["compose"] and "config" in a:'))
        self.assertEqual(self.run_estimator()["default"]["unknown"], [])

    def test_record_appends_one_line(self):
        self.run_estimator("--record")
        with open(self.history) as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["kind"], "estimate")
        self.assertIn("date", record)


class DockerfileTest(unittest.TestCase):
    def parse(self, text, args=None, target=None):
        path = os.path.join(tempfile.mkdtemp(), "Dockerfile")
        with open(path, "w") as fh:
            fh.write(text)
        return install_size.dockerfile_images(path, args or {}, target)

    def test_stages_args_and_external_copy_sources(self):
        self.assertEqual(self.parse(
            "ARG V=1\nFROM --platform=$X node:${V}-slim AS build\nRUN a \\\n  && b\n"
            "FROM busybox AS artifact\nCOPY --from=build /a /a\nCOPY --from=ghcr.io/x/uv:latest /uv /uv\n"
            "RUN --mount=type=bind,from=build,target=/w true\n"),
            ["node:1-slim", "busybox", "ghcr.io/x/uv:latest"])

    def test_stages_after_the_target_are_not_built(self):
        self.assertEqual(self.parse("FROM a AS one\nFROM b AS two\nFROM c AS three\n", target="two"), ["a", "b"])

    def test_a_build_arg_overrides_the_default(self):
        self.assertEqual(self.parse("ARG TAG=old\nFROM img:${TAG}\n", {"TAG": "new"}), ["img:new"])

    def test_scratch_and_earlier_stage_names_are_not_images(self):
        self.assertEqual(self.parse("FROM scratch AS s\nFROM s\n"), [])


class LedgerTest(Base):
    def run_verify(self, **extra):
        work = os.path.join(self.tmp, "work")
        os.makedirs(work, exist_ok=True)
        for name in ("docker-compose.yaml", ".env"):
            open(os.path.join(work, name), "w").close()
        proc = subprocess.run(["bash", VERIFY], capture_output=True, text=True, cwd=work, timeout=120,
                              env=self.env(INSTALL_SIZE_DEVICE="test-box", INSTALL_SIZE_NOTE="unit test", **extra))
        return proc

    def records(self):
        with open(self.history) as fh:
            return [json.loads(l) for l in fh.read().splitlines()]

    def test_a_run_appends_one_record_with_the_numbers(self):
        proc = self.run_verify(BUDGET_GB="100")
        self.assertIn("recorded to " + self.history, proc.stdout)
        (record,) = self.records()
        self.assertEqual(record["kind"], "fresh-install")
        self.assertEqual(record["images_gb"], 0.6)
        self.assertEqual(record["volumes_gb"], 0.01)
        self.assertEqual(record["build_cache_gb"], 1.5)
        self.assertEqual(record["budget_gb"], 100.0)
        self.assertTrue(record["within_budget"])
        self.assertEqual(record["device"], "test-box")
        self.assertEqual(record["note"], "unit test")
        self.assertEqual(record["docker"], {"server": "99.0.0", "compose": "9.9.9"})
        self.assertEqual([r["image"] for r in record["per_image"]], ["app-a:1"])
        self.assertAlmostEqual(record["total_gb"], record["images_gb"] + record["volumes_gb"] + record["repo_gb"], places=2)

    def test_recording_never_changes_the_verdict(self):
        # Over budget fails the script, and the record is still written and says so.
        proc = self.run_verify(BUDGET_GB="0.1")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("over budget", proc.stdout)
        self.assertFalse(self.records()[0]["within_budget"])

    def test_an_unwritable_history_is_reported_and_the_run_carries_on(self):
        blocked = os.path.join(self.tmp, "blocked")
        open(blocked, "w").close()
        proc = self.run_verify(BUDGET_GB="0.1", INSTALL_SIZE_HISTORY=os.path.join(blocked, "h.jsonl"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("over budget", proc.stdout)
        self.assertIn("ledger", proc.stdout)

    def test_an_empty_history_variable_records_nothing(self):
        proc = self.run_verify(BUDGET_GB="100", INSTALL_SIZE_HISTORY="")
        self.assertIn("history disabled", proc.stdout)
        self.assertFalse(os.path.exists(self.history))


if __name__ == "__main__":
    unittest.main()
