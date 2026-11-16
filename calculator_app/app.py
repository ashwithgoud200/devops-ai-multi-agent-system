"""Sample target app: a calculator API with Prometheus metrics, JSON logs,
deploy history and an admin API the agents can use."""
import inspect, json, logging, math, os, sys, time, uuid
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from agents import llm_runtime
from agents import metrics as app_metrics
from agents.chatops_api import router as chatops_router
from agents.memory_api import router as memory_router
from agents.chaos_engine import chaos_engine
from agents.chaos_api import router as chaos_router
from agents.docker_telemetry import collect_docker_metrics
from agents.feature_api import router as feature_router
from agents.incident_api import router as incident_router
from agents.integration_api import router as integration_router
from agents.scenario_api import router as scenario_router
from agents import scenarios
from agents import remote_app_client
from agents.prometheus_telemetry import collect_prometheus_metrics
from agents.loki_client import push_loki_log
from agents.tempo_client import record_trace_span

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_env_file():
    if "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ or any("pytest" in arg.lower() for arg in sys.argv):
        return
    env_file = os.path.join(ROOT, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass

_load_env_file()
LOG_PATH = os.getenv("DEVOPS_LOG_PATH", os.path.join(ROOT, "logs", "app.log"))
os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
logger = logging.getLogger("calc")
logger.setLevel(logging.INFO)
logger.addHandler(logging.FileHandler(LOG_PATH))

def log(level, **kw):
    entry = {"ts": time.time(), "level": level, **kw}
    line = json.dumps(entry)
    logger.info(line)
    try:
        push_loki_log(level=level, msg=line, labels={"version": STATE.get("version", "1.0")})
    except Exception:
        pass

REQ = Counter("calc_requests_total", "Calculator requests", ["op", "status"])
LAT = Histogram("calc_latency_seconds", "Calculator latency", ["op"])
OPS = {"add": lambda a, b: a + b, "sub": lambda a, b: a - b,
       "mul": lambda a, b: a * b, "div": lambda a, b: a / b, "pow": lambda a, b: a ** b}
STATE = {"version": "1.0", "bug": False,
         "history": [{"version": "1.0", "ts": time.time()}]}
app = FastAPI(title="Calculator")
app.add_middleware(GZipMiddleware, minimum_size=500)
app.include_router(incident_router)
app.include_router(integration_router)
app.include_router(scenario_router)
app.include_router(feature_router)
app.include_router(chatops_router)
app.include_router(memory_router)
app.include_router(chaos_router)


@app.middleware("http")
async def prometheus_http_middleware(request: Request, call_next):
    started_perf = time.perf_counter()
    started_wall = time.time()
    trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or request.url.path
        duration = time.perf_counter() - started_perf
        app_metrics.record_http_request(
            endpoint=route_path,
            method=request.method,
            status_code=status_code,
            duration_seconds=duration,
        )
        try:
            record_trace_span(
                trace_id=trace_id,
                span_id=span_id,
                name=f"{request.method} {request.url.path}",
                start_time=started_wall,
                end_time=time.time(),
                status_code=status_code,
                attributes={
                    "http.method": request.method,
                    "http.route": route_path,
                    "http.url": str(request.url),
                },
            )
        except Exception:
            pass

@app.get("/calc/{op}")
def calc(op: str, a: float, b: float = 0.0):
    # Check for real chaos latency or legacy scenario latency before dispatching
    chaos_delay = chaos_engine.get_active_latency()
    injected_delay = max(chaos_delay, scenarios.get_injected_latency())
    if injected_delay > 0:
        time.sleep(injected_delay)

    # Check for real chaos crash mode
    crash_active, crash_msg = chaos_engine.is_crash_mode_active()
    if crash_active:
        REQ.labels(op, "error").inc()
        log("ERROR", op=op, msg=crash_msg)
        raise HTTPException(status_code=500, detail=crash_msg)

    # Check for deployment regression bug
    if STATE.get("bug") and op == "div":
        REQ.labels(op, "error").inc()
        err_msg = f"v{STATE['version']} regression: div handler crashed"
        log("ERROR", op=op, msg=err_msg)
        raise HTTPException(status_code=500, detail=err_msg)

    # Attempt forwarding to standalone Code-Agent Calculator microservice
    target_url = os.getenv("DEVOPS_APP_URL", "http://127.0.0.1:8100").rstrip("/")
    try:
        import requests
        resp = requests.get(f"{target_url}/calc/{op}", params={"a": a, "b": b}, timeout=3.0)
        if resp.status_code in (200, 400, 404, 500):
            status_tag = "ok" if resp.status_code == 200 else "client_error" if resp.status_code == 400 else "error"
            REQ.labels(op, status_tag).inc()
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", resp.text))
            return resp.json()
    except (requests.RequestException, HTTPException) as re_exc:
        if isinstance(re_exc, HTTPException):
            raise re_exc
        # Microservice not reachable; fallback to control plane local execution
        pass

    if op not in OPS:
        raise HTTPException(404, "unknown op")
    start = time.time()
    try:
        fn = OPS[op]
        sig = inspect.signature(fn)
        if len(sig.parameters) == 1:
            result = fn(a)
        else:
            result = fn(a, b)
        REQ.labels(op, "ok").inc()
        log("INFO", op=op, a=a, b=b, result=result, version=STATE["version"])
        return {"op": op, "result": result, "version": STATE["version"]}
    except ZeroDivisionError:
        REQ.labels(op, "client_error").inc()
        log("WARN", op=op, msg="division by zero (user input)")
        raise HTTPException(400, "division by zero")
    except ValueError as ve:
        REQ.labels(op, "client_error").inc()
        log("WARN", op=op, msg=str(ve))
        raise HTTPException(400, str(ve))
    except Exception as e:
        REQ.labels(op, "error").inc()
        log("ERROR", op=op, msg=str(e), version=STATE["version"])
        raise HTTPException(500, str(e))
    finally:
        LAT.labels(op).observe(time.time() - start)

@app.get("/health")
def health():
    """Liveness/readiness endpoint used by Docker and deployment checks."""
    app_metrics.APP_HEALTH_STATUS.set(1)
    chaos_status = chaos_engine.get_status()
    if chaos_status["active_experiments_count"] > 0:
        exp_names = ", ".join(chaos_status["active_experiments"].keys())
        return {"status": "degraded", "version": STATE["version"], "detail": f"Active chaos experiments: {exp_names}"}
    if scenarios.is_fault_active("infra_degraded"):
        return {"status": "degraded", "version": STATE["version"], "detail": "simulated container infrastructure pressure"}
    return {"status": "ok", "version": STATE["version"]}


@app.get("/metrics")
def metrics():
    app_metrics.APP_HEALTH_STATUS.set(1)
    try:
        cfg = llm_runtime.load_config()
        app_metrics.LLM_ENABLED_STATUS.set(1 if cfg.get("enabled", False) else 0)
    except Exception:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/telemetry/docker")
def docker_telemetry():
    """Return read-only container metrics without exposing Docker controls."""
    return collect_docker_metrics()


@app.get("/telemetry/prometheus")
def prometheus_telemetry():
    """Return read-only time-series observations from the configured Prometheus API."""
    return collect_prometheus_metrics()


@app.get("/admin/version")
def version():
    return {"version": STATE["version"], "history": STATE["history"]}

@app.post("/admin/deploy")
def deploy(version: str, bug: bool = False):
    STATE.update(version=version, bug=bug)
    STATE["history"].append({"version": version, "ts": time.time()})
    log("INFO", msg=f"deployed v{version}")
    remote_app_client.remote_deploy(version=version, bug=bug)
    return {"deployed": version, "bug": bug}

@app.post("/admin/rollback")
def rollback():
    prev = STATE["history"][-2]["version"] if len(STATE["history"]) > 1 else "1.0"
    STATE.update(version=prev, bug=False)
    STATE["history"].append({"version": prev, "ts": time.time()})
    scenarios.reset_scenario(calculator_state=STATE)
    log("INFO", msg=f"rolled back to v{prev}")
    remote_app_client.remote_rollback()
    remote_app_client.remote_reset_faults()
    return {"rolled_back_to": prev}


# Serve built React dashboard when present (for production/Render deployments)
FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_frontend_index():
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        return {"status": "ok", "app": "Calculator DevOps API", "version": STATE["version"]}
else:
    @app.get("/")
    def serve_root():
        return {"status": "ok", "app": "Calculator DevOps API", "version": STATE["version"]}

