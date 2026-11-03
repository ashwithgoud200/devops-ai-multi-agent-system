"""Sample target app: a calculator API with Prometheus metrics, JSON logs,
deploy history and an admin API the agents can use."""
import json, logging, os, time
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from agents import llm_runtime
from agents import metrics as app_metrics
from agents.docker_telemetry import collect_docker_metrics
from agents.incident_api import router as incident_router
from agents.integration_api import router as integration_router
from agents.prometheus_telemetry import collect_prometheus_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.getenv("DEVOPS_LOG_PATH", os.path.join(ROOT, "logs", "app.log"))
os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
logger = logging.getLogger("calc")
logger.setLevel(logging.INFO)
logger.addHandler(logging.FileHandler(LOG_PATH))

def log(level, **kw):
    logger.info(json.dumps({"ts": time.time(), "level": level, **kw}))

REQ = Counter("calc_requests_total", "Calculator requests", ["op", "status"])
LAT = Histogram("calc_latency_seconds", "Calculator latency", ["op"])
OPS = {"add": lambda a, b: a + b, "sub": lambda a, b: a - b,
       "mul": lambda a, b: a * b, "div": lambda a, b: a / b, "pow": lambda a, b: a ** b}
STATE = {"version": "1.0", "bug": False,
         "history": [{"version": "1.0", "ts": time.time()}]}
app = FastAPI(title="Calculator")
app.include_router(incident_router)
app.include_router(integration_router)


@app.middleware("http")
async def prometheus_http_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None)
        app_metrics.record_http_request(
            endpoint=route_path,
            method=request.method,
            status_code=status_code,
            duration_seconds=time.perf_counter() - started,
        )

@app.get("/calc/{op}")
def calc(op: str, a: float, b: float):
    if op not in OPS:
        raise HTTPException(404, "unknown op")
    start = time.time()
    try:
        if STATE["bug"] and op == "div":
            raise RuntimeError(f"v{STATE['version']} regression: div handler crashed")
        result = OPS[op](a, b)
        REQ.labels(op, "ok").inc()
        log("INFO", op=op, a=a, b=b, result=result, version=STATE["version"])
        return {"op": op, "result": result, "version": STATE["version"]}
    except ZeroDivisionError:
        REQ.labels(op, "client_error").inc()
        log("WARN", op=op, msg="division by zero (user input)")
        raise HTTPException(400, "division by zero")
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
    return {"deployed": version}

@app.post("/admin/rollback")
def rollback():
    prev = STATE["history"][-2]["version"] if len(STATE["history"]) > 1 else "1.0"
    STATE.update(version=prev, bug=False)
    STATE["history"].append({"version": prev, "ts": time.time()})
    log("INFO", msg=f"rolled back to v{prev}")
    return {"rolled_back_to": prev}
