"""FastAPI endpoints for Chaos Engineering and Real Fault Injection."""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.chaos_engine import chaos_engine

logger = logging.getLogger("chaos_api")

router = APIRouter(prefix="/chaos", tags=["Chaos Engineering"])


class CpuStressRequest(BaseModel):
    duration_seconds: int = Field(default=15, ge=1, le=120, description="Duration to burn CPU cycles")
    num_threads: int = Field(default=2, ge=1, le=8, description="Number of worker threads")


class MemoryStressRequest(BaseModel):
    megabytes: int = Field(default=200, ge=10, le=500, description="Megabytes of RAM to allocate")
    duration_seconds: int = Field(default=15, ge=1, le=120, description="Duration to hold memory")


class LatencyInjectionRequest(BaseModel):
    latency_seconds: float = Field(default=0.45, ge=0.05, le=5.0, description="HTTP latency delay in seconds")
    duration_seconds: int = Field(default=20, ge=1, le=180, description="Duration to maintain latency")


class CrashModeRequest(BaseModel):
    arm: bool = Field(default=True, description="Whether to arm or disarm crash mode")
    message: str = Field(
        default="Real Chaos Exception: unhandled runtime fault in Calculator service",
        description="Exception message to raise",
    )


@router.get("/status", summary="Get status of active chaos experiments and live host telemetry")
def get_chaos_status() -> dict[str, Any]:
    """Return status of all active chaos experiments and physical host telemetry."""
    return chaos_engine.get_status()


@router.post("/stress/cpu", summary="Trigger real physical CPU stress")
def stress_cpu(req: CpuStressRequest = CpuStressRequest()) -> dict[str, Any]:
    """Spawn real threads executing CPU-bound calculations to elevate physical CPU load."""
    return chaos_engine.trigger_cpu_stress(
        duration_seconds=req.duration_seconds,
        num_threads=req.num_threads,
    )


@router.post("/stress/memory", summary="Trigger real physical memory pressure")
def stress_memory(req: MemoryStressRequest = MemoryStressRequest()) -> dict[str, Any]:
    """Allocate real memory byte arrays to induce genuine host memory pressure."""
    return chaos_engine.trigger_memory_stress(
        megabytes=req.megabytes,
        duration_seconds=req.duration_seconds,
    )


@router.post("/inject/latency", summary="Inject real HTTP response latency")
def inject_latency(req: LatencyInjectionRequest = LatencyInjectionRequest()) -> dict[str, Any]:
    """Add genuine I/O delay to application endpoints."""
    return chaos_engine.trigger_latency_spike(
        latency_seconds=req.latency_seconds,
        duration_seconds=req.duration_seconds,
    )


@router.post("/trigger/crash", summary="Arm real application crash mode")
def arm_crash(req: CrashModeRequest = CrashModeRequest()) -> dict[str, Any]:
    """Arm the application to raise genuine unhandled Python exceptions on incoming requests."""
    return chaos_engine.trigger_crash_mode(active=req.arm, message=req.message)


@router.post("/run/security-audit", summary="Run live dependency security audit")
def run_security_audit() -> dict[str, Any]:
    """Audit project dependencies and security report files."""
    return chaos_engine.run_security_audit()


@router.post("/stop", summary="Stop all active chaos experiments")
def stop_all_chaos() -> dict[str, Any]:
    """Immediately halt CPU stress, release memory, and clear injected latency."""
    return chaos_engine.stop_all()

