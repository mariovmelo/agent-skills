"""
Memory monitoring utilities for uai.

Uses /proc/self/status and /proc/meminfo (Linux) to measure process RSS
and system free memory without external dependencies.

Enable debug output by setting UAI_MEM_DEBUG=1.
"""
from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass, field

_DEBUG = os.environ.get("UAI_MEM_DEBUG", "").strip() not in ("", "0", "false")
_log = logging.getLogger("uai.memmon")

# Minimum free system memory (MB) before we skip spawning extra subprocesses.
# With no swap, going below this risks OOM kill.
MEM_CRITICAL_MB = int(os.environ.get("UAI_MEM_CRITICAL_MB", "150"))


@dataclass
class MemSnapshot:
    label: str
    rss_mb: float          # process RSS
    avail_mb: float        # system available memory
    ts: float = field(default_factory=time.monotonic)

    def __str__(self) -> str:
        return (
            f"[memmon] {self.label}: "
            f"proc_rss={self.rss_mb:.1f}MB  sys_avail={self.avail_mb:.1f}MB"
        )


def _read_proc_self_status() -> dict[str, int]:
    """Parse /proc/self/status into a dict of kB values."""
    result: dict[str, int] = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if ":" in line:
                    k, _, v = line.partition(":")
                    v = v.strip()
                    if v.endswith(" kB"):
                        try:
                            result[k.strip()] = int(v[:-3])
                        except ValueError:
                            pass
    except OSError:
        pass
    return result


def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of kB values."""
    result: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if ":" in line:
                    k, _, v = line.partition(":")
                    v = v.strip()
                    if v.endswith(" kB"):
                        try:
                            result[k.strip()] = int(v[:-3])
                        except ValueError:
                            pass
    except OSError:
        pass
    return result


def snapshot(label: str = "") -> MemSnapshot:
    """Take a memory snapshot and optionally log it."""
    proc = _read_proc_self_status()
    meminfo = _read_meminfo()

    rss_mb = proc.get("VmRSS", 0) / 1024
    avail_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024

    snap = MemSnapshot(label=label, rss_mb=rss_mb, avail_mb=avail_mb)
    if _DEBUG:
        _log.debug(str(snap))
        print(str(snap), flush=True)
    return snap


def is_memory_critical() -> bool:
    """Return True when system available memory is below MEM_CRITICAL_MB."""
    meminfo = _read_meminfo()
    avail_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
    critical = avail_mb < MEM_CRITICAL_MB
    if critical and _DEBUG:
        _log.warning(
            "[memmon] CRITICAL: only %.1fMB available (threshold %dMB)",
            avail_mb,
            MEM_CRITICAL_MB,
        )
    return critical


def log_delta(before: MemSnapshot, after: MemSnapshot, label: str = "") -> None:
    """Log the difference between two snapshots."""
    drss = after.rss_mb - before.rss_mb
    davail = after.avail_mb - before.avail_mb
    elapsed = after.ts - before.ts
    msg = (
        f"[memmon] {label or after.label}: "
        f"Δrss={drss:+.1f}MB  Δavail={davail:+.1f}MB  "
        f"avail_after={after.avail_mb:.1f}MB  elapsed={elapsed:.2f}s"
    )
    if _DEBUG:
        _log.debug(msg)
        print(msg, flush=True)
    else:
        _log.debug(msg)
