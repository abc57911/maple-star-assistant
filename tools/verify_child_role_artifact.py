from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.app.child_roles import ChildRoleBootstrap, probe_child_imports
from maple_star.ipc.identity import WorkerRole
from maple_star.services.benchmark_environment import collect_benchmark_environment


def run_verification(timeout_seconds: float = 10.0) -> dict[str, object]:
    context = mp.get_context("spawn")
    result_queue = context.Queue()
    session = uuid.uuid4().hex
    roles = (
        WorkerRole.GUARDIAN,
        WorkerRole.SCHEDULER,
        WorkerRole.POTION,
        WorkerRole.EXPERIENCE,
        WorkerRole.NOTIFICATION,
    )
    processes = []
    for role in roles:
        bootstrap = ChildRoleBootstrap(session, role, 1, os.getpid())
        process = context.Process(target=probe_child_imports, args=(bootstrap, result_queue), daemon=False)
        process.start()
        processes.append(process)
    for process in processes:
        process.join(timeout=timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
    results = [result_queue.get(timeout=1.0) for _ in processes]
    exitcodes = [process.exitcode for process in processes]
    passed = all(code == 0 for code in exitcodes) and all(
        not result["loaded_forbidden_modules"] for result in results
    )
    return {
        "marker": "child-role-import-isolation",
        "roles": results,
        "exitcodes": exitcodes,
        "passed": passed,
        "environment": collect_benchmark_environment(
            mode="python-spawn", cache_condition="cold-process", root=ROOT
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="verify spawned child role import isolation")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    result = run_verification(max(1.0, args.timeout))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
