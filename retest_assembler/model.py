"""Type definitions and input validation for the assembly library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Question:
    """A question in the pool."""

    id: str
    difficulty: int  # 1..5
    topics: FrozenSet[str]


@dataclass(frozen=True)
class Quota:
    """Inclusive integer range [minimum, maximum]."""

    minimum: int
    maximum: int


@dataclass(frozen=True)
class AssemblyRequest:
    """All inputs needed to assemble one paper."""

    questions: Tuple[Question, ...]
    count: int
    topic_quotas: Mapping[str, Quota]
    difficulty_quotas: Mapping[int, Quota]
    required: FrozenSet[str]
    banned: FrozenSet[str]
    history: Tuple[FrozenSet[str], ...]
    seed: int


@dataclass(frozen=True)
class Selection:
    """One selected question and its single counting topic."""

    question_id: str
    counting_topic: str


@dataclass(frozen=True)
class Assembly:
    """A successfully assembled paper."""

    selections: Tuple[Selection, ...]


class NoSolution:
    """Explicit sentinel returned when no legal paper exists."""

    _instance: Optional["NoSolution"] = None

    def __new__(cls) -> "NoSolution":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NO_SOLUTION"

    def __bool__(self) -> bool:
        return False


NO_SOLUTION = NoSolution()


def validate_request(request: AssemblyRequest) -> None:
    """Raise ValueError on malformed input (infeasibility is NOT an error)."""
    ids = [q.id for q in request.questions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question id in pool")
    for q in request.questions:
        if not isinstance(q.id, str) or not q.id:
            raise ValueError("question id must be a non-empty string")
        if not 1 <= q.difficulty <= 5:
            raise ValueError(f"question {q.id!r}: difficulty must be in 1..5")
        if not q.topics:
            raise ValueError(f"question {q.id!r}: needs at least one topic")
    if request.count < 0:
        raise ValueError("count must be non-negative")
    if request.seed < 0:
        raise ValueError("seed must be a non-negative integer")
    for name, quotas in (("topic", request.topic_quotas),
                         ("difficulty", request.difficulty_quotas)):
        for key, quota in quotas.items():
            if quota.minimum < 0 or quota.maximum < quota.minimum:
                raise ValueError(f"invalid {name} quota for {key!r}")
    pool_ids = set(ids)
    unknown_required = request.required - pool_ids
    if unknown_required:
        raise ValueError(f"required ids not in pool: {sorted(unknown_required)}")
    unknown_banned = request.banned - pool_ids
    if unknown_banned:
        raise ValueError(f"banned ids not in pool: {sorted(unknown_banned)}")
