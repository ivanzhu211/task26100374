"""Core assembly algorithm.

Exact dynamic programming over (selected count, topic counts, difficulty
counts). Costs are lexicographic integer triples:

1. number of selected questions that appear in any historical paper,
2. total historical occurrence count of selected questions,
3. sum of per-question random costs derived from the seed.

Ties are broken deterministically (questions and topics are processed in
sorted order and the first best candidate is kept), so the result depends
only on the input *set* and the seed, never on input ordering.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple, Union

from .model import (
    Assembly,
    AssemblyRequest,
    NO_SOLUTION,
    NoSolution,
    Selection,
    validate_request,
)

_Cost = Tuple[int, int, int]
_State = Tuple[int, Tuple[int, ...], Tuple[int, ...]]
# parent: (previous state, taken question id, counting topic or None)
_Parent = Optional[Tuple[_State, str, Optional[str]]]


def _random_cost(seed: int, question_id: str) -> int:
    payload = f"{seed}:{question_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def assemble(request: AssemblyRequest) -> Union[Assembly, NoSolution]:
    """Assemble one optimal paper, or return NO_SOLUTION."""
    validate_request(request)

    topics = sorted(request.topic_quotas)
    difficulties = sorted(request.difficulty_quotas)
    topic_index = {t: i for i, t in enumerate(topics)}
    diff_index = {d: i for i, d in enumerate(difficulties)}
    topic_max = tuple(request.topic_quotas[t].maximum for t in topics)
    diff_max = tuple(request.difficulty_quotas[d].maximum for d in difficulties)

    history_count: Dict[str, int] = {}
    for paper in request.history:
        for qid in paper:
            history_count[qid] = history_count.get(qid, 0) + 1

    eligible = sorted(
        (q for q in request.questions if q.id not in request.banned),
        key=lambda q: q.id,
    )

    zero = (0, (0,) * len(topics), (0,) * len(difficulties))
    layer: Dict[_State, Tuple[_Cost, _Parent]] = {zero: ((0, 0, 0), None)}
    layers: List[Dict[_State, Tuple[_Cost, _Parent]]] = [layer]

    for question in eligible:
        prev = layers[-1]
        required = question.id in request.required
        current: Dict[_State, Tuple[_Cost, _Parent]] = {}
        if not required:
            for state, entry in prev.items():
                current[state] = (entry[0], (state, question.id, None))
        hist = history_count.get(question.id, 0)
        step_cost: _Cost = (1 if hist else 0, hist,
                            _random_cost(request.seed, question.id))
        t_idx = [topic_index[t] for t in sorted(question.topics)
                 if t in topic_index]
        d_idx = diff_index.get(question.difficulty)
        for state, (base_cost, _) in sorted(prev.items()):
            n, t_counts, d_counts = state
            if n + 1 > request.count:
                continue
            if d_idx is not None and d_counts[d_idx] + 1 > diff_max[d_idx]:
                continue
            new_cost = (base_cost[0] + step_cost[0],
                        base_cost[1] + step_cost[1],
                        base_cost[2] + step_cost[2])
            new_d = (d_counts if d_idx is None else
                     d_counts[:d_idx] + (d_counts[d_idx] + 1,) + d_counts[d_idx + 1:])
            topic_choices = sorted(question.topics) if t_idx else [None]
            for topic in topic_choices:
                if topic is None or topic not in topic_index:
                    new_t = t_counts
                else:
                    i = topic_index[topic]
                    if t_counts[i] + 1 > topic_max[i]:
                        continue
                    new_t = t_counts[:i] + (t_counts[i] + 1,) + t_counts[i + 1:]
                new_state = (n + 1, new_t, new_d)
                existing = current.get(new_state)
                if existing is None or new_cost < existing[0]:
                    current[new_state] = (
                        new_cost, (state, question.id, topic))
        layers.append(current)

    final = layers[-1]
    best_state: Optional[_State] = None
    best_cost: Optional[_Cost] = None
    for state in sorted(final):
        n, t_counts, d_counts = state
        if n != request.count:
            continue
        if any(t_counts[i] < request.topic_quotas[t].minimum
               for i, t in enumerate(topics)):
            continue
        if any(d_counts[i] < request.difficulty_quotas[d].minimum
               for i, d in enumerate(difficulties)):
            continue
        cost = final[state][0]
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_state = state

    if best_state is None:
        return NO_SOLUTION

    selections: List[Selection] = []
    state = best_state
    for layer_index in range(len(layers) - 1, 0, -1):
        parent = layers[layer_index][state][1]
        assert parent is not None
        prev_state, qid, topic = parent
        if topic is not None:
            selections.append(Selection(qid, topic))
        state = prev_state
    selections.sort(key=lambda s: s.question_id)
    return Assembly(tuple(selections))
