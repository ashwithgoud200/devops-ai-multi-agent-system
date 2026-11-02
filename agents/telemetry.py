"""Dependency-free host CPU and memory telemetry."""
from __future__ import annotations

import ctypes
import sys
import time
from typing import Any


def _linux_cpu_times() -> tuple[int, int]:
    with open("/proc/stat", encoding="ascii") as stat_file:
        fields = stat_file.readline().split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("Invalid /proc/stat CPU counters")
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values[:8]), idle


def _linux_memory() -> tuple[int, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as memory_file:
        for line in memory_file:
            name, separator, remainder = line.partition(":")
            if separator and name in {"MemTotal", "MemAvailable"}:
                values[name] = int(remainder.split()[0])
    total = values["MemTotal"]
    available = values["MemAvailable"]
    if total <= 0 or available < 0 or available > total:
        raise ValueError("Invalid /proc/meminfo memory counters")
    return total, available


def _windows_cpu_times() -> tuple[int, int]:
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

        def as_integer(self) -> int:
            return (self.high << 32) | self.low

    idle, kernel, user = FileTime(), FileTime(), FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        raise OSError("GetSystemTimes failed")
    return kernel.as_integer() + user.as_integer(), idle.as_integer()


def _windows_memory() -> tuple[int, int]:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("memory_load", ctypes.c_uint32),
            ("total_physical", ctypes.c_uint64),
            ("available_physical", ctypes.c_uint64),
            ("total_page_file", ctypes.c_uint64),
            ("available_page_file", ctypes.c_uint64),
            ("total_virtual", ctypes.c_uint64),
            ("available_virtual", ctypes.c_uint64),
            ("available_extended_virtual", ctypes.c_uint64),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return int(status.total_physical), int(status.available_physical)


def _read_cpu_times() -> tuple[int, int]:
    if sys.platform.startswith("linux"):
        return _linux_cpu_times()
    if sys.platform == "win32":
        return _windows_cpu_times()
    raise OSError(f"Host CPU telemetry is unsupported on {sys.platform}")


def _read_memory() -> tuple[int, int]:
    if sys.platform.startswith("linux"):
        return _linux_memory()
    if sys.platform == "win32":
        return _windows_memory()
    raise OSError(f"Host memory telemetry is unsupported on {sys.platform}")


def collect_system_metrics(sample_interval: float = 0.1) -> dict[str, Any]:
    """Measure host utilization; failed measurements remain explicitly unavailable."""
    measurements: dict[str, Any] = {}
    errors = []
    timestamp = time.time()
    try:
        first_total, first_idle = _read_cpu_times()
        time.sleep(sample_interval)
        second_total, second_idle = _read_cpu_times()
        total_delta = second_total - first_total
        idle_delta = second_idle - first_idle
        if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
            raise ValueError("Invalid CPU counter delta")
        measurements["cpu_utilization_percent"] = (
            (total_delta - idle_delta) / total_delta * 100
        )
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"CPU: {exc}")

    try:
        total_memory, available_memory = _read_memory()
        if total_memory <= 0:
            raise ValueError("Total memory must be positive")
        measurements["memory_utilization_percent"] = (
            (total_memory - available_memory) / total_memory * 100
        )
        measurements["memory_total_bytes"] = total_memory
        measurements["memory_available_bytes"] = available_memory
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"Memory: {exc}")

    timestamp = time.time()
    status = "ok" if not errors else "partial" if measurements else "unavailable"
    return {
        "status": status,
        "source": (
            "host OS: /proc/stat and /proc/meminfo"
            if sys.platform.startswith("linux")
            else "host OS: Windows GetSystemTimes and GlobalMemoryStatusEx"
            if sys.platform == "win32"
            else f"unsupported platform {sys.platform}"
        ),
        "timestamp": timestamp,
        "measurements": measurements,
        "detail": "; ".join(errors) if errors else None,
    }
