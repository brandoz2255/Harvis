"""P5.1 isolation unit test — create a scratch agent workspace, write a file in
it (as a tool would), collect the diff + changed files, exercise path-safety,
and clean up. Run in the backend container:

    docker cp python_back_end/tests/test_orchestration_isolation.py harvis-backend:/tmp/t.py
    docker exec -e PYTHONPATH=/app harvis-backend python3 /tmp/t.py
"""

import asyncio
import os

from workspace.orchestration.isolation import (
    WorkspaceIsolationManager,
    validate_agent_path,
)


async def main() -> None:
    m = WorkspaceIsolationManager()
    ws = await m.create_workspace_for_agent("unittest-iso-001", role="backend")
    p = ws["workspace_path"]

    # Simulate an agent tool writing a file inside its workspace.
    with open(os.path.join(p, "hello.py"), "w") as f:
        f.write("print('hi from agent')\n")

    files = await m.collect_changed_files(p)
    diff = await m.collect_diff(p)

    checks = {
        "workspace_created": os.path.isdir(p),
        "branch_set": ws["branch_name"].startswith("agent-backend-"),
        "changed_files_eq_hello": files == ["hello.py"],
        "diff_has_content": ("hello.py" in diff) and ("hi from agent" in diff),
        "path_ok_inside": validate_agent_path(p, "sub/dir/x.txt") is True,
        "path_block_dotdot": validate_agent_path(p, "../../etc/passwd") is False,
        "path_block_absolute": validate_agent_path(p, "/etc/passwd") is False,
    }

    await m.cleanup(p)
    checks["cleaned_up"] = not os.path.exists(p)

    print("workspace_path:", p)
    print("branch:", ws["branch_name"])
    print("changed_files:", files)
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    if all(checks.values()):
        print("RESULT: ALL PASS")
    else:
        print("RESULT: FAILURES PRESENT")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
