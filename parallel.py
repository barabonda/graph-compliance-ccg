"""Bounded, deterministic fan-out helper for the CCG review pipeline.

The review pipeline performs several independent read fan-outs (per-anchor Neo4j
candidate retrieval, disjoint claim-chunk extraction, per-judgment exception
override). Each fan-out is embarrassingly parallel — the items do not depend on
one another and the merge is keyed/ordered deterministically by the caller.

This module centralizes two concerns:

1. Concurrency caps come from env only (no hardcoded fan-out width). A global
   master cap ``CCG_PARALLEL_WORKERS`` bounds every fan-out; setting it to ``1``
   forces fully sequential execution (a debugging / determinism escape hatch).
   Each fan-out also has its own per-site env key with a sensible default.
2. Result ordering is deterministic: ``ordered_parallel_map`` returns results in
   the exact order of the input items, regardless of completion order, so the
   parallel path produces byte-identical merges to the previous sequential path.

Failure contract: exceptions raised by a worker are re-raised to the caller
(the first failing item in input order), never swallowed. This preserves the
project's "fail loud, no silent fallback" contract.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Global master cap env key. When set to a positive int it bounds every fan-out;
# 1 => sequential everywhere. Unset (or non-positive) means "no master override,
# use each site's own cap".
MASTER_WORKERS_ENV = "CCG_PARALLEL_WORKERS"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def worker_count(env_key: str, default: int) -> int:
    """Resolve the worker cap for a fan-out site.

    Precedence: the site-specific ``env_key`` (falling back to ``default``) is
    capped by the global ``CCG_PARALLEL_WORKERS`` master when the master is set
    to a positive value. A master of 1 therefore forces sequential execution at
    every site. The returned value is always >= 1.
    """
    site = _int_env(env_key, default)
    master = _int_env(MASTER_WORKERS_ENV, 0)
    workers = site
    if master >= 1:
        workers = min(workers, master)
    return max(1, workers)


def ordered_parallel_map(
    fn: Callable[[T], R],
    items: Sequence[T],
    *,
    workers: int,
    label: str = "",
) -> list[R]:
    """Apply ``fn`` to each item, returning results in input order.

    Runs sequentially when ``workers <= 1`` or there is at most one item (the
    debug / trivial path). Otherwise submits all items to a bounded
    ``ThreadPoolExecutor`` and collects results by submission index, so the
    returned list matches ``items`` order exactly no matter which worker finishes
    first. Worker exceptions propagate to the caller (first failing index),
    preserving the loud-failure contract.
    """
    total = len(items)
    if workers <= 1 or total <= 1:
        return [fn(item) for item in items]

    effective_workers = min(workers, total)
    if label:
        LOGGER.info("parallel.start label=%s items=%d workers=%d", label, total, effective_workers)
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = [executor.submit(fn, item) for item in items]
        # Reading results in submission order keeps the merge deterministic and
        # re-raises the first failing item's exception (in input order).
        results = [future.result() for future in futures]
    if label:
        LOGGER.info("parallel.done label=%s items=%d", label, total)
    return results
