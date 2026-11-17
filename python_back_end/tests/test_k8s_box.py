"""Chat boxes as Kubernetes pods (workspace/k8s_box.py): the pod spec and the pure helpers."""

import pytest

from workspace import k8s_box

CFG = {"ns": "harvis-boxes", "pvc": "harvis-box-sandboxes", "root": "/data/artifacts/sandboxes",
       "node": "n1", "image": "harvis-repo-sandbox:local", "mem": "1024m", "cpu": "1.0", "disk": "10G"}


def test_pod_meets_restricted_pod_security():
    pod = k8s_box.pod_manifest("hs-u1-abc", "u1/chat", CFG)
    spec = pod["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    c = spec["containers"][0]
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert c["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert all("hostPath" not in v for v in spec["volumes"])
    assert "hostNetwork" not in spec and "hostPID" not in spec


def test_pod_mounts_only_its_own_chat_folder():
    c = k8s_box.pod_manifest("hs-u1-abc", "u1/chat", CFG)["spec"]["containers"][0]
    assert c["volumeMounts"] == [{"name": "chat", "mountPath": "/workspace", "subPath": "u1/chat"}]


def test_limits_use_kubernetes_quantities():
    limits = k8s_box.pod_manifest("k", "u1/c", CFG)["spec"]["containers"][0]["resources"]["limits"]
    assert limits == {"memory": "1024Mi", "cpu": "1.0", "ephemeral-storage": "10Gi"}


def test_pod_names_are_dns_safe_and_distinct():
    a, b = k8s_box.pod_name("hs-u1-" + "a" * 60), k8s_box.pod_name("hs-u1-" + "a" * 61)
    for n in (a, b, k8s_box.pod_name("VC:Weird_Key")):
        assert len(n) <= 63 and n == n.lower() and n[0].isalnum() and n[-1].isalnum()
    assert a != b


def test_subpath_refuses_paths_outside_the_chat_folders(tmp_path):
    root = tmp_path / "sandboxes"
    (root / "u1" / "chat").mkdir(parents=True)
    assert k8s_box.subpath_of(str(root / "u1" / "chat"), str(root)) == "u1/chat"
    for bad in (str(tmp_path), str(root), str(root / "u1" / ".." / ".." / "etc"), "/etc"):
        with pytest.raises(k8s_box.BoxError):
            k8s_box.subpath_of(bad, str(root))


@pytest.mark.parametrize("status,code", [
    ('{"status":"Success"}', 0),
    ('{"status":"Failure","reason":"NonZeroExitCode","details":{"causes":[{"reason":"ExitCode","message":"2"}]}}', 2),
    ('{"status":"Failure","message":"container not found"}', -1),
    ("", -1),
])
def test_exit_code_from_the_error_channel(status, code):
    assert k8s_box.exit_code_of(status) == code


def test_exec_command_is_url_encoded():
    path = k8s_box._exec_path("ns", "p", ["sh", "-c", "echo a&b=c"])
    assert "command=echo%20a%26b%3Dc" in path and "container=box" in path


def test_box_image_is_never_pulled_from_a_registry():
    c = k8s_box.pod_manifest("k", "u1/c", CFG)["spec"]["containers"][0]
    assert c["imagePullPolicy"] == "Never"


def test_a_failed_box_is_not_retried_for_a_minute(monkeypatch, tmp_path):
    import asyncio

    root = tmp_path / "sandboxes"
    (root / "u1" / "c").mkdir(parents=True)
    monkeypatch.setenv("HARVIS_K8S_BOX_ROOT", str(root))
    calls = []

    async def boom(cfg, key, name, sub):
        calls.append(name)
        raise k8s_box.BoxError(k8s_box._explain("ErrImageNeverPull"))

    monkeypatch.setattr(k8s_box, "_ensure", boom)
    k8s_box._failed.clear()
    for _ in range(3):
        with pytest.raises(k8s_box.BoxError, match="install.sh --k8s"):
            asyncio.run(k8s_box.ensure("hs-u1-x", str(root / "u1" / "c")))
    assert len(calls) == 1
