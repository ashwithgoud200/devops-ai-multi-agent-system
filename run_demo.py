import argparse
import os
import random
import subprocess
import sys
import time

import requests
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from agents import graph as G

DEMO_HOST = os.getenv("DEVOPS_DEMO_HOST", "127.0.0.1")
DEMO_PORT = int(os.getenv("DEVOPS_DEMO_PORT", "8100"))
BASE = f"http://{DEMO_HOST}:{DEMO_PORT}"

def traffic(
    n,
    ops=("add", "sub", "mul", "div", "pow"),
    expected_statuses=(200,),
):
    server_errors = 0
    for _ in range(n):
        response = requests.get(
            f"{BASE}/calc/{random.choice(ops)}",
            params={"a": random.randint(1, 50), "b": random.randint(1, 9)},
            timeout=5,
        )
        if response.status_code not in expected_statuses:
            response.raise_for_status()
            raise RuntimeError(
                f"Unexpected calculator HTTP status: {response.status_code}"
            )
        server_errors += response.status_code >= 500
    return server_errors

def run(query, decide, tid):
    g = G.build()
    cfg: RunnableConfig = {"configurable": {"thread_id": tid}}
    inp: G.IncidentState | Command[object] = {"query": query, "trace": []}
    while True:
        pending = None
        for chunk in g.stream(inp, cfg, stream_mode="updates"):
            for node, upd in chunk.items():
                if node == "__interrupt__":
                    pending = upd[0].value
                elif upd:
                    for line in upd.get("trace", []): print(line)
        if pending is None: return
        print(f"\n>>> APPROVAL REQUIRED: {pending['action']}  (cause: {pending['root_cause']})")
        d = decide(pending)
        print(f">>> decision: {'approve' if d else 'reject'}\n")
        inp = Command(resume=d)


def _approval_decision(approve=False, reject=False, pending=None):
    if approve:
        return True
    if reject:
        return False
    action = pending.get("action", "the proposed action") if pending else "the action"
    answer = input(
        f"Type 'approve' to execute {action}, or anything else to reject: "
    )
    return answer.strip().lower() == "approve"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve a proposed rollback when the demo pauses.",
    )
    decision.add_argument(
        "--reject",
        action="store_true",
        help="Explicitly reject a proposed rollback when the demo pauses.",
    )
    args = parser.parse_args()
    os.environ["DEVOPS_APP_URL"] = BASE
    srv = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "calculator_app.app:app",
        "--host", DEMO_HOST, "--port", str(DEMO_PORT), "--log-level", "warning",
    ])
    try:
        for _ in range(50):
            if srv.poll() is not None:
                raise RuntimeError(
                    f"Demo API exited before becoming ready (exit code {srv.returncode})."
                )
            try:
                response = requests.get(f"{BASE}/metrics", timeout=1)
                response.raise_for_status()
                time.sleep(0.1)
                if srv.poll() is not None:
                    raise RuntimeError(
                        f"Demo API exited before becoming ready (exit code {srv.returncode})."
                    )
                break
            except requests.RequestException:
                time.sleep(0.2)
        else:
            raise TimeoutError(f"Demo API did not become ready at {BASE}.")
        print("== 1. healthy traffic on calculator v1.0"); traffic(60)
        G.save_baseline()
        print("== 2. CI/CD ships v1.1 with a hidden bug in division"); time.sleep(1)
        deployment = requests.post(
            f"{BASE}/admin/deploy",
            params={"version": "1.1", "bug": "true"},
            timeout=5,
        )
        deployment.raise_for_status()
        expected_errors = traffic(
            20,
            ops=("div",),
            expected_statuses=(500,),
        )
        if expected_errors != 20:
            raise RuntimeError(
                f"Expected 20 synthetic division errors, observed {expected_errors}."
            )
        print("== 3. user asks the supervisor: 'calculator is throwing errors, what is wrong?'\n")

        def decide(pending):
            return _approval_decision(args.approve, args.reject, pending)

        run("calculator is throwing errors, what is wrong?", decide, "demo")
    finally:
        if srv.poll() is None:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except subprocess.TimeoutExpired:
                srv.kill()
                srv.wait()
