"""Reproducible exam paper assembly with topic/difficulty quotas.

Pure standard library. See README.md for usage.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple, Union

__all__ = [
    "Question",
    "Interval",
    "Assignment",
    "AssembleResult",
    "assemble",
]


@dataclass(frozen=True)
class Interval:
    """Closed integer interval [min, max]."""

    min: int
    max: int

    def __post_init__(self) -> None:
        if isinstance(self.min, bool) or isinstance(self.max, bool):
            raise ValueError("interval bounds must be integers")
        if not isinstance(self.min, int) or not isinstance(self.max, int):
            raise ValueError("interval bounds must be integers")
        if self.min < 0 or self.max < self.min:
            raise ValueError("interval must satisfy 0 <= min <= max")


@dataclass(frozen=True)
class Question:
    """A candidate question: unique id, difficulty 1..5, one or more tags."""

    id: str
    difficulty: int
    tags: frozenset

    def __init__(self, id: str, difficulty: int, tags: Iterable[str]) -> None:
        if not isinstance(id, str) or not id:
            raise ValueError("question id must be a non-empty string")
        if isinstance(difficulty, bool) or not isinstance(difficulty, int):
            raise ValueError("difficulty must be an integer in 1..5")
        if not 1 <= difficulty <= 5:
            raise ValueError("difficulty must be in 1..5")
        tag_set = frozenset(tags)
        if not tag_set or not all(isinstance(t, str) and t for t in tag_set):
            raise ValueError("tags must be one or more non-empty strings")
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "difficulty", difficulty)
        object.__setattr__(self, "tags", tag_set)


@dataclass(frozen=True)
class Assignment:
    """A selected question and the single topic it counts toward."""

    question_id: str
    topic: str


@dataclass(frozen=True)
class AssembleResult:
    """Assembly outcome. ``ok`` is False when no legal paper exists."""

    ok: bool
    assignments: Tuple[Assignment, ...]

    @property
    def question_ids(self) -> Tuple[str, ...]:
        return tuple(a.question_id for a in self.assignments)


def assemble(
    questions: Iterable[Question],
    count: int,
    topic_quotas: Mapping[str, Union[Interval, Tuple[int, int]]],
    difficulty_quotas: Mapping[int, Union[Interval, Tuple[int, int]]],
    required: Iterable[str] = (),
    forbidden: Iterable[str] = (),
    history: Iterable[Iterable[str]] = (),
    seed: int = 0,
) -> AssembleResult:
    """Assemble one optimal paper or report infeasibility.

    Among all legal papers the cost is minimized lexicographically:
    (number of selected questions seen in any historical paper,
     total historical appearances of selected questions,
     total SHA-256 random cost of selected questions).
    The result is deterministic for the same input multiset and seed.
    """
    pool, topics, tq, dq, must, banned, hist = _validate(
        questions, count, topic_quotas, difficulty_quotas,
        required, forbidden, seed,
    )
    for paper in history:
        for qid in paper:
            if qid in pool:
                hist[qid] += 1

    t_index = {t: i for i, t in enumerate(topics)}
    t_lo = tuple(tq[t].min for t in topics)
    t_hi = tuple(tq[t].max for t in topics)
    d_lo = tuple(dq[d].min for d in range(1, 6))
    d_hi = tuple(dq[d].max for d in range(1, 6))

    items = []
    for q in sorted(pool.values(), key=lambda x: x.id):
        if q.id in banned:
            continue
        appearances = hist.get(q.id, 0)
        cost = (
            1 if appearances else 0,
            appearances,
            _random_cost(seed, q.id),
        )
        items.append((q, cost, q.id in must))

    # State: (selected, difficulty_counts, topic_counts) -> (cost, assignments).
    # Counts are exact; transitions that would exceed any quota upper bound
    # or the paper size are dropped since they can never become legal.
    start = (0, (0,) * 5, (0,) * len(topics))
    states = {start: ((0, 0, 0), ())}
    for q, cost, is_required in items:
        nxt = {} if is_required else dict(states)
        d_slot = q.difficulty - 1
        for (total, d_counts, t_counts), (acc, chosen) in states.items():
            if total == count or d_counts[d_slot] == d_hi[d_slot]:
                continue
            new_d = list(d_counts)
            new_d[d_slot] += 1
            new_d = tuple(new_d)
            for tag in sorted(q.tags):
                t_slot = t_index[tag]
                if t_counts[t_slot] == t_hi[t_slot]:
                    continue
                new_t = list(t_counts)
                new_t[t_slot] += 1
                state = (total + 1, new_d, tuple(new_t))
                new_cost = (acc[0] + cost[0], acc[1] + cost[1],
                            acc[2] + cost[2])
                current = nxt.get(state)
                if current is None or new_cost < current[0]:
                    nxt[state] = (new_cost, chosen + ((q.id, tag),))
        states = nxt
        if not states:
            break

    best = None
    for (total, d_counts, t_counts), (acc, chosen) in states.items():
        if total != count:
            continue
        if any(d_counts[i] < d_lo[i] for i in range(5)):
            continue
        if any(t_counts[j] < t_lo[j] for j in range(len(topics))):
            continue
        if best is None or acc < best[0]:
            best = (acc, chosen)

    if best is None:
        return AssembleResult(False, ())
    assignments = tuple(
        Assignment(qid, tag)
        for qid, tag in sorted(best[1])
    )
    return AssembleResult(True, assignments)


def _random_cost(seed: int, question_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{question_id}".encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


def _as_interval(value, name: str) -> Interval:
    if isinstance(value, Interval):
        return value
    try:
        lo, hi = value
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an Interval or (min, max) pair")
    return Interval(lo, hi)


def _validate(questions, count, topic_quotas, difficulty_quotas,
              required, forbidden, seed):
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a non-negative integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    pool = {}
    for q in questions:
        if not isinstance(q, Question):
            raise ValueError("questions must be Question instances")
        if q.id in pool:
            raise ValueError(f"duplicate question id: {q.id!r}")
        pool[q.id] = q

    tq = {t: _as_interval(v, f"topic quota {t!r}")
          for t, v in topic_quotas.items()}
    for q in pool.values():
        unknown = q.tags - tq.keys()
        if unknown:
            raise ValueError(
                f"question {q.id!r} has tags without quotas: "
                f"{sorted(unknown)!r}")

    dq = {}
    for d, v in difficulty_quotas.items():
        if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 5:
            raise ValueError("difficulty quota keys must be integers 1..5")
        dq[d] = _as_interval(v, f"difficulty quota {d!r}")
    if set(dq) != {1, 2, 3, 4, 5}:
        raise ValueError("difficulty quotas must cover difficulties 1..5")

    must = frozenset(required)
    banned = frozenset(forbidden)
    for name, group in (("required", must), ("forbidden", banned)):
        unknown = group - pool.keys()
        if unknown:
            raise ValueError(
                f"{name} contains unknown question ids: "
                f"{sorted(unknown)!r}")
    if must & banned:
        raise ValueError(
            f"questions both required and forbidden: "
            f"{sorted(must & banned)!r}")

    topics = sorted(tq)
    return pool, topics, tq, dq, must, banned, Counter()
