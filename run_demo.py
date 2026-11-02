import os, subprocess, sys, time, requests, random
from langgraph.types import Command
from agents import graph as G

DEMO_HOST = os.getenv("DEVOPS_DEMO_HOST", "127.0.0.1")
DEMO_PORT = int(os.getenv("DEVOPS_DEMO_PORT", "8100"))
BASE = f"http://{DEMO_HOST}:{DEMO_PORT}"

def traffic(n, ops=("add", "sub", "mul", "div", "pow")):
    for _ in range(n):
        requests.get(f"{BASE}/calc/{random.choice(ops)}", params={"a": random.randint(1, 50), "b": random.randint(1, 9)})

def run(query, decide, tid):
    g, cfg, inp = G.build(), {"configurable": {"thread_id": tid}}, {"query": query, "trace": []}
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

if __name__ == "__main__":
    approve = "--reject" not in sys.argv
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
        requests.post(f"{BASE}/admin/deploy", params={"version": "1.1", "bug": "true"}); traffic(80)
        print("== 3. user asks the supervisor: 'calculator is throwing errors, what is wrong?'\n")
        run("calculator is throwing errors, what is wrong?", lambda p: approve, "demo")
    finally:
        if srv.poll() is None:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except subprocess.TimeoutExpired:
                srv.kill()
                srv.wait()
