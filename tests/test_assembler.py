"""Tests for the retest assembly library."""

import hashlib
import itertools
import random
import unittest

from retest_assembler import (
    NO_SOLUTION,
    Assembly,
    AssemblyRequest,
    Question,
    Quota,
    assemble,
)


def make_request(questions, count, topic_quotas, difficulty_quotas,
                 required=(), banned=(), history=(), seed=0):
    return AssemblyRequest(
        questions=tuple(questions),
        count=count,
        topic_quotas=topic_quotas,
        difficulty_quotas=difficulty_quotas,
        required=frozenset(required),
        banned=frozenset(banned),
        history=tuple(frozenset(p) for p in history),
        seed=seed,
    )


def random_cost(seed, qid):
    return int.from_bytes(
        hashlib.sha256(f"{seed}:{qid}".encode("utf-8")).digest(), "big")


def history_counts(history):
    counts = {}
    for paper in history:
        for qid in paper:
            counts[qid] = counts.get(qid, 0) + 1
    return counts


def cost_of(selection_ids, history, seed):
    counts = history_counts(history)
    seen = sum(1 for qid in selection_ids if counts.get(qid))
    total = sum(counts.get(qid, 0) for qid in selection_ids)
    rand = sum(random_cost(seed, qid) for qid in selection_ids)
    return (seen, total, rand)


def check_valid(testcase, request, assembly):
    """Assert an Assembly satisfies every hard constraint."""
    testcase.assertIsInstance(assembly, Assembly)
    sels = assembly.selections
    ids = [s.question_id for s in sels]
    testcase.assertEqual(len(ids), len(set(ids)), "duplicate questions")
    testcase.assertEqual(len(ids), request.count)
    pool = {q.id: q for q in request.questions}
    for sel in sels:
        testcase.assertIn(sel.question_id, pool)
        testcase.assertIn(sel.counting_topic, pool[sel.question_id].topics)
        testcase.assertNotIn(sel.question_id, request.banned)
    testcase.assertTrue(request.required <= set(ids))
    for topic, quota in request.topic_quotas.items():
        n = sum(1 for s in sels if s.counting_topic == topic)
        testcase.assertTrue(quota.minimum <= n <= quota.maximum,
                            f"topic {topic}: {n}")
    for diff, quota in request.difficulty_quotas.items():
        n = sum(1 for s in sels if pool[s.question_id].difficulty == diff)
        testcase.assertTrue(quota.minimum <= n <= quota.maximum,
                            f"difficulty {diff}: {n}")


def brute_force(request):
    """Reference: enumerate every subset and every legal topic assignment.

    Returns (best_cost, best_assignment_set) or None.
    """
    eligible = [q for q in request.questions if q.id not in request.banned]
    by_id = {q.id: q for q in eligible}
    best_cost = None
    best_assignment = None
    for combo in itertools.combinations(sorted(by_id), request.count):
        if not request.required <= set(combo):
            continue
        questions = [by_id[i] for i in combo]
        topic_lists = [sorted(q.topics) for q in questions]
        for assignment in itertools.product(*topic_lists):
            ok = True
            for topic, quota in request.topic_quotas.items():
                n = sum(1 for t in assignment if t == topic)
                if not quota.minimum <= n <= quota.maximum:
                    ok = False
                    break
            if not ok:
                continue
            for diff, quota in request.difficulty_quotas.items():
                n = sum(1 for q in questions if q.difficulty == diff)
                if not quota.minimum <= n <= quota.maximum:
                    ok = False
                    break
            if not ok:
                continue
            cost = cost_of(combo, request.history, request.seed)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_assignment = frozenset(zip(combo, assignment))
    if best_cost is None:
        return None
    return best_cost, best_assignment


class CrossQuotaTest(unittest.TestCase):
    def test_reassignment_required_banned(self):
        # q1 owns topics {A, B} but must count toward A: q2 can only count
        # A and q3 only B, while A needs exactly 2 and B exactly 1.
        questions = (
            Question("q1", 1, frozenset({"A", "B"})),
            Question("q2", 1, frozenset({"A"})),
            Question("q3", 2, frozenset({"B"})),
            Question("q4", 2, frozenset({"A", "B"})),
        )
        request = make_request(
            questions, 3,
            {"A": Quota(2, 2), "B": Quota(1, 1)},
            {1: Quota(2, 2), 2: Quota(1, 1)},
            required={"q1"}, banned={"q4"},
        )
        result = assemble(request)
        check_valid(self, request, result)
        assignment = {s.question_id: s.counting_topic
                      for s in result.selections}
        self.assertEqual(assignment, {"q1": "A", "q2": "A", "q3": "B"})

    def test_individually_feasible_jointly_infeasible(self):
        # Topic quotas alone: q1+q3 works. Difficulty quotas alone:
        # q1+q2 works. Together: impossible.
        questions = (
            Question("q1", 1, frozenset({"A"})),
            Question("q2", 1, frozenset({"A"})),
            Question("q3", 2, frozenset({"B"})),
        )
        request = make_request(
            questions, 2,
            {"A": Quota(1, 2), "B": Quota(1, 1)},
            {1: Quota(2, 2), 2: Quota(0, 0)},
        )
        self.assertIs(assemble(request), NO_SOLUTION)


class BruteForceComparisonTest(unittest.TestCase):
    SCENARIOS = []

    def build_scenarios(self):
        base = [
            Question("a", 1, frozenset({"X"})),
            Question("b", 1, frozenset({"X", "Y"})),
            Question("c", 2, frozenset({"Y"})),
            Question("d", 2, frozenset({"X", "Y"})),
            Question("e", 3, frozenset({"X"})),
            Question("f", 3, frozenset({"Y"})),
        ]
        scenarios = []
        # History unavoidable: every selectable question appears in history.
        scenarios.append(make_request(
            base, 3,
            {"X": Quota(1, 2), "Y": Quota(1, 2)},
            {1: Quota(0, 2), 2: Quota(0, 2), 3: Quota(0, 2)},
            history=[{"a", "b", "c"}, {"a", "d"}, {"a", "e", "f"}],
            seed=7,
        ))
        # Required + banned + history mix.
        scenarios.append(make_request(
            base, 4,
            {"X": Quota(2, 3), "Y": Quota(1, 2)},
            {1: Quota(1, 2), 2: Quota(1, 2), 3: Quota(1, 2)},
            required={"f"}, banned={"a"},
            history=[{"b", "c"}, {"b"}],
            seed=13,
        ))
        # No history at all.
        scenarios.append(make_request(
            base, 2,
            {"X": Quota(0, 2), "Y": Quota(0, 2)},
            {1: Quota(0, 1), 2: Quota(0, 1), 3: Quota(0, 1)},
            seed=99,
        ))
        return scenarios

    def test_matches_brute_force(self):
        for request in self.build_scenarios():
            with self.subTest(seed=request.seed):
                expected = brute_force(request)
                result = assemble(request)
                if expected is None:
                    self.assertIs(result, NO_SOLUTION)
                    continue
                best_cost, _ = expected
                check_valid(self, request, result)
                ids = [s.question_id for s in result.selections]
                self.assertEqual(
                    cost_of(ids, request.history, request.seed), best_cost)

    def test_random_small_pools(self):
        rng = random.Random(2024)
        topics = ["X", "Y", "Z"]
        for trial in range(30):
            n_questions = rng.randint(3, 7)
            questions = [
                Question(
                    f"q{i}",
                    rng.randint(1, 3),
                    frozenset(rng.sample(topics, rng.randint(1, 2))),
                )
                for i in range(n_questions)
            ]
            count = rng.randint(1, n_questions)
            topic_quotas = {t: Quota(0, count) for t in topics}
            topic_quotas[rng.choice(topics)] = Quota(1, count)
            diff_quotas = {d: Quota(0, count) for d in (1, 2, 3)}
            history = [
                {q.id for q in questions if rng.random() < 0.4}
                for _ in range(rng.randint(0, 3))
            ]
            request = make_request(
                questions, count, topic_quotas, diff_quotas,
                history=history, seed=rng.randint(0, 1000),
            )
            expected = brute_force(request)
            result = assemble(request)
            if expected is None:
                self.assertIs(result, NO_SOLUTION, f"trial {trial}")
            else:
                best_cost, _ = expected
                check_valid(self, request, result)
                ids = [s.question_id for s in result.selections]
                self.assertEqual(
                    cost_of(ids, request.history, request.seed),
                    best_cost, f"trial {trial}")


class ReproducibilityTest(unittest.TestCase):
    def test_shuffled_inputs_give_identical_result(self):
        questions = [
            Question("a", 1, frozenset({"X", "Y"})),
            Question("b", 1, frozenset({"X"})),
            Question("c", 2, frozenset({"Y"})),
            Question("d", 2, frozenset({"X", "Y"})),
            Question("e", 3, frozenset({"Y"})),
            Question("f", 3, frozenset({"X"})),
        ]
        history = [{"a", "c"}, {"c", "e"}, {"a"}]
        rng = random.Random(42)
        results = []
        for _ in range(10):
            qs = questions[:]
            rng.shuffle(qs)
            hs = [set(p) for p in history]
            rng.shuffle(hs)
            topic_items = [("X", Quota(2, 3)), ("Y", Quota(2, 3))]
            rng.shuffle(topic_items)
            request = make_request(
                qs, 4, dict(topic_items),
                {1: Quota(1, 2), 2: Quota(1, 2), 3: Quota(0, 2)},
                history=hs, seed=5,
            )
            results.append(assemble(request))
        first = results[0]
        check_valid(self, request, first)
        for other in results[1:]:
            self.assertEqual(first, other)

    def test_random_cost_definition(self):
        self.assertEqual(
            random_cost(7, "q12"),
            int.from_bytes(hashlib.sha256(b"7:q12").digest(), "big"),
        )

    def test_history_is_not_a_ban(self):
        questions = (
            Question("q1", 1, frozenset({"A"})),
            Question("q2", 1, frozenset({"A"})),
        )
        request = make_request(
            questions, 1, {"A": Quota(1, 1)}, {1: Quota(1, 1)},
            history=[{"q1"}, {"q1"}], seed=0,
        )
        result = assemble(request)
        check_valid(self, request, result)
        # q2 has zero history, so it must be preferred.
        self.assertEqual([s.question_id for s in result.selections], ["q2"])

    def test_history_occurrences_counted_per_paper(self):
        # q1 appears in two papers (count 2), q2 in one (count 1); both
        # force equal first-level cost, so the second level decides.
        questions = (
            Question("q1", 1, frozenset({"A"})),
            Question("q2", 1, frozenset({"A"})),
        )
        request = make_request(
            questions, 1, {"A": Quota(1, 1)}, {1: Quota(1, 1)},
            history=[{"q1"}, {"q1", "q2"}], seed=0,
        )
        result = assemble(request)
        self.assertEqual([s.question_id for s in result.selections], ["q2"])


class ValidationTest(unittest.TestCase):
    def test_duplicate_ids_rejected(self):
        questions = (
            Question("q1", 1, frozenset({"A"})),
            Question("q1", 2, frozenset({"B"})),
        )
        request = make_request(questions, 1, {"A": Quota(0, 1)}, {})
        with self.assertRaises(ValueError):
            assemble(request)

    def test_unknown_required_rejected(self):
        request = make_request(
            (Question("q1", 1, frozenset({"A"})),), 1,
            {"A": Quota(0, 1)}, {}, required={"nope"},
        )
        with self.assertRaises(ValueError):
            assemble(request)

    def test_required_and_banned_is_infeasible(self):
        questions = (Question("q1", 1, frozenset({"A"})),)
        request = make_request(
            questions, 1, {"A": Quota(1, 1)}, {1: Quota(1, 1)},
            required={"q1"}, banned={"q1"},
        )
        self.assertIs(assemble(request), NO_SOLUTION)


if __name__ == "__main__":
    unittest.main()
