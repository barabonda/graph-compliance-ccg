"""Unit tests for the deterministic parallel fan-out helper and its use in the
review pipeline (change A: CU candidate retrieval, change C: exception override).

All tests are stub-based (no live LLM/Neo4j). They assert that the parallel path
preserves input order under out-of-order completion, honors the concurrency cap
env, and re-raises worker failures (loud-failure contract).
"""

from __future__ import annotations

import threading
import time

import pytest

from parallel import ordered_parallel_map, worker_count


def test_ordered_parallel_map_preserves_input_order_under_reordered_completion() -> None:
    # Later items sleep less, so they finish first; the result must still be in
    # input order, proving the merge is index-keyed, not completion-keyed.
    items = list(range(6))

    def slow(value: int) -> int:
        time.sleep((6 - value) * 0.01)
        return value * 10

    result = ordered_parallel_map(slow, items, workers=6)

    assert result == [value * 10 for value in items]


def test_ordered_parallel_map_actually_runs_in_parallel() -> None:
    # A barrier of width N only releases if N workers run concurrently; if the
    # helper were sequential this would deadlock (guarded by a timeout).
    width = 4
    barrier = threading.Barrier(width, timeout=5)

    def wait_at_barrier(value: int) -> int:
        barrier.wait()
        return value

    result = ordered_parallel_map(wait_at_barrier, list(range(width)), workers=width)

    assert result == list(range(width))


def test_ordered_parallel_map_sequential_when_single_worker() -> None:
    order: list[int] = []

    def record(value: int) -> int:
        order.append(value)
        return value

    result = ordered_parallel_map(record, [3, 1, 2], workers=1)

    # workers=1 => strict sequential in input order (debug path).
    assert result == [3, 1, 2]
    assert order == [3, 1, 2]


def test_ordered_parallel_map_reraises_first_failure_in_input_order() -> None:
    def maybe_fail(value: int) -> int:
        if value == 2:
            raise ValueError("boom at 2")
        time.sleep(0.01)
        return value

    with pytest.raises(ValueError, match="boom at 2"):
        ordered_parallel_map(maybe_fail, [0, 1, 2, 3], workers=4)


def test_ordered_parallel_map_empty_items() -> None:
    assert ordered_parallel_map(lambda item: item, [], workers=4) == []


def test_worker_count_uses_site_default_without_master(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCG_PARALLEL_WORKERS", raising=False)
    monkeypatch.delenv("CCG_PARALLEL_NEO4J_WORKERS", raising=False)

    assert worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6) == 6


def test_worker_count_site_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCG_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("CCG_PARALLEL_NEO4J_WORKERS", "3")

    assert worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6) == 3


def test_worker_count_master_caps_every_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCG_PARALLEL_WORKERS", "2")
    monkeypatch.setenv("CCG_PARALLEL_NEO4J_WORKERS", "8")

    # Master (2) caps the site value (8).
    assert worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6) == 2


def test_worker_count_master_one_forces_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCG_PARALLEL_WORKERS", "1")
    monkeypatch.setenv("CCG_PARALLEL_CLAIM_WORKERS", "4")

    assert worker_count("CCG_PARALLEL_CLAIM_WORKERS", 4) == 1


def test_worker_count_never_below_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCG_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("CCG_PARALLEL_NEO4J_WORKERS", "0")

    assert worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6) == 1


def test_worker_count_ignores_non_integer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCG_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("CCG_PARALLEL_NEO4J_WORKERS", "not-a-number")

    assert worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6) == 6


# --- Merge-idiom tests: mirror exactly how workflow.py reassembles results -----


def test_change_a_candidate_merge_keys_by_anchor_under_reordered_completion() -> None:
    # Mirrors workflow change A: candidates fetched per anchor in parallel, then
    # rebuilt into {anchor_id: result} by enumerate index. Later anchors finish
    # first (reversed sleep), yet each anchor_id must map to its own result.
    anchor_ids = [f"anchor_{i}" for i in range(5)]

    def fetch(anchor_id: str) -> list[str]:
        index = int(anchor_id.split("_")[1])
        time.sleep((5 - index) * 0.01)
        # Encode the anchor_id into the "candidate" so mis-keying is detectable.
        return [f"cu_for_{anchor_id}"]

    candidate_lists = ordered_parallel_map(fetch, anchor_ids, workers=5)
    candidates_by_anchor = {
        anchor_id: candidate_lists[index] for index, anchor_id in enumerate(anchor_ids)
    }

    assert candidates_by_anchor == {
        anchor_id: [f"cu_for_{anchor_id}"] for anchor_id in anchor_ids
    }


def test_change_c_exception_reassembly_preserves_order_and_drops_none() -> None:
    # Mirrors workflow change C: eligible judgments reviewed in parallel; some
    # return None (no mitigation evidence) and must be dropped while surviving
    # reviews stay in eligible (input) order despite reordered completion.
    eligible = list(range(6))

    def review(value: int) -> str | None:
        time.sleep((6 - value) * 0.01)
        if value % 2 == 0:
            return None  # no mitigation evidence -> skipped, as sequential loop did
        return f"review_{value}"

    review_results = ordered_parallel_map(review, eligible, workers=6)
    exception_reviews = [review for review in review_results if review is not None]

    assert exception_reviews == ["review_1", "review_3", "review_5"]
