"""Tests for examgen. Run: python3 -m unittest test_examgen -v"""

import hashlib
import itertools
import random
import unittest
from collections import Counter

from examgen import (
    AssembleResult,
    Assignment,
    Interval,
    Question,
    assemble,
)


def random_cost(seed, qid):
    digest = hashlib.sha256(f"{seed}:{qid}".encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


def full_difficulty_quotas(overrides=()):
    quotas = {d: Interval(0, 100) for d in range(1, 6)}
    quotas.update(overrides)
    return quotas


def cost_of(ids, history, seed):
    hist = Counter(qid for paper in history for qid in paper)
    return (
        sum(1 for qid in ids if hist[qid]),
        sum(hist[qid] for qid in ids),
        sum(random_cost(seed, qid) for qid in ids),
    )


def check_valid(test, result, pool, count, topic_quotas,
                difficulty_quotas, required, forbidden):
    test.assertTrue(result.ok)
    test.assertEqual(len(result.assignments), count)
    by_id = {q.id: q for q in pool}
    ids = [a.question_id for a in result.assignments]
    test.assertEqual(len(set(ids)), count, "questions must be distinct")
    topic_counts = Counter()
    difficulty_counts = Counter()
    for a in result.assignments:
        q = by_id[a.question_id]
        test.assertIn(a.topic, q.tags)
        topic_counts[a.topic] += 1
        difficulty_counts[q.difficulty] += 1
    for topic, quota in topic_quotas.items():
        test.assertLessEqual(quota.min, topic_counts[topic])
        test.assertLessEqual(topic_counts[topic], quota.max)
    for d, quota in difficulty_quotas.items():
        test.assertLessEqual(quota.min, difficulty_counts[d])
        test.assertLessEqual(difficulty_counts[d], quota.max)
    test.assertTrue(set(required) <= set(ids))
    test.assertFalse(set(forbidden) & set(ids))


def brute_force(pool, count, topic_quotas, difficulty_quotas,
                required, forbidden, history, seed):
    """Reference optimum: enumerate every subset and tag assignment."""
    candidates = [q for q in pool if q.id not in set(forbidden)]
    required = set(required)
    best = None
    for combo in itertools.combinations(candidates, count):
        if not required <= {q.id for q in combo}:
            continue
        for tags in itertools.product(*(sorted(q.tags) for q in combo)):
            t_counts = Counter(tags)
            d_counts = Counter(q.difficulty for q in combo)
            if not all(q_.min <= t_counts[t] <= q_.max
                       for t, q_ in topic_quotas.items()):
                continue
            if not all(q_.min <= d_counts[d] <= q_.max
                       for d, q_ in difficulty_quotas.items()):
                continue
            cost = cost_of([q.id for q in combo], history, seed)
            if best is None or cost < best:
                best = cost
    return best


class TestScenarios(unittest.TestCase):
    def test_multitag_assignment_switch_with_required_and_forbidden(self):
        # q2 has tags {A, B}; quotas force it to count toward B, not A.
        pool = [
            Question("q1", 1, {"A"}),
            Question("q2", 2, {"A", "B"}),
            Question("q3", 2, {"B"}),
        ]
        topic_quotas = {"A": Interval(1, 1), "B": Interval(1, 1)}
        difficulty_quotas = full_difficulty_quotas(
            {1: Interval(1, 1), 2: Interval(1, 1)})
        result = assemble(pool, 2, topic_quotas, difficulty_quotas,
                          required={"q1"}, forbidden={"q3"}, seed=7)
        check_valid(self, result, pool, 2, topic_quotas, difficulty_quotas,
                    {"q1"}, {"q3"})
        self.assertEqual(
            {a.question_id: a.topic for a in result.assignments},
            {"q1": "A", "q2": "B"},
        )

    def test_individually_satisfiable_jointly_infeasible(self):
        # Every quota alone has enough candidates, but B's only candidate
        # is difficulty 2 while both slots must be difficulty 1.
        pool = [
            Question("q1", 1, {"A"}),
            Question("q2", 1, {"A"}),
            Question("q3", 2, {"B"}),
        ]
        topic_quotas = {"A": Interval(1, 1), "B": Interval(1, 1)}
        difficulty_quotas = full_difficulty_quotas({1: Interval(2, 2)})
        result = assemble(pool, 2, topic_quotas, difficulty_quotas, seed=0)
        self.assertFalse(result.ok)
        self.assertEqual(result.assignments, ())
        self.assertEqual(result.question_ids, ())


class TestCostPriority(unittest.TestCase):
    def setUp(self):
        self.topic_quotas = {"A": Interval(1, 1)}
        self.difficulty_quotas = full_difficulty_quotas({1: Interval(1, 1)})

    def pick(self, pool, history, seed=0):
        result = assemble(pool, 1, self.topic_quotas,
                          self.difficulty_quotas, history=history, seed=seed)
        self.assertTrue(result.ok)
        return result.question_ids[0]

    def test_unseen_beats_seen_regardless_of_random_cost(self):
        pool = [Question("seen", 1, {"A"}), Question("fresh", 1, {"A"})]
        winner = self.pick(pool, history=[{"seen"}], seed=0)
        self.assertEqual(winner, "fresh")

    def test_fewer_appearances_beats_more(self):
        pool = [Question("twice", 1, {"A"}), Question("once", 1, {"A"})]
        history = [{"twice", "once"}, {"twice"}]
        winner = self.pick(pool, history=history, seed=0)
        self.assertEqual(winner, "once")

    def test_random_cost_breaks_ties(self):
        pool = [Question("x", 1, {"A"}), Question("y", 1, {"A"})]
        seed = 42
        expected = min(("x", "y"), key=lambda qid: random_cost(seed, qid))
        winner = self.pick(pool, history=[], seed=seed)
        self.assertEqual(winner, expected)

    def test_seen_count_precedes_appearance_count(self):
        # {u, popular} has 1 seen question but 5 appearances; {a, b} has
        # 2 seen questions but only 2 appearances. Level 1 wins, so the
        # paper must be {u, popular} despite the higher appearance count.
        # Topic and difficulty quotas together make these the only two
        # feasible papers.
        pool = [
            Question("u", 1, {"Z"}),
            Question("popular", 2, {"Y"}),
            Question("a", 1, {"Y"}),
            Question("b", 2, {"Z"}),
        ]
        topic_quotas = {"Z": Interval(1, 1), "Y": Interval(1, 1)}
        difficulty_quotas = full_difficulty_quotas(
            {1: Interval(1, 1), 2: Interval(1, 1)})
        history = [{"popular"} for _ in range(5)] + [{"a"}, {"b"}]
        result = assemble(pool, 2, topic_quotas, difficulty_quotas,
                          history=history, seed=0)
        self.assertTrue(result.ok)
        self.assertEqual(set(result.question_ids), {"u", "popular"})


class TestBruteForce(unittest.TestCase):
    def test_history_unavoidable_and_shuffled_reproducible(self):
        # Every legal paper must include q1 and q2, both seen in history.
        pool = [
            Question("q1", 1, {"A"}),
            Question("q2", 2, {"B"}),
            Question("q3", 3, {"C"}),
            Question("q4", 3, {"C"}),
        ]
        topic_quotas = {
            "A": Interval(1, 1),
            "B": Interval(1, 1),
            "C": Interval(1, 1),
        }
        difficulty_quotas = full_difficulty_quotas(
            {1: Interval(1, 1), 2: Interval(1, 1), 3: Interval(1, 1)})
        history = [{"q1", "q2"}, {"q1"}]
        seed = 99
        reference = assemble(pool, 3, topic_quotas, difficulty_quotas,
                             history=history, seed=seed)
        self.assertTrue(reference.ok)
        check_valid(self, reference, pool, 3, topic_quotas,
                    difficulty_quotas, (), ())
        ids = set(reference.question_ids)
        self.assertTrue({"q1", "q2"} <= ids, "history overlap unavoidable")
        self.assertEqual(
            cost_of(reference.question_ids, history, seed),
            brute_force(pool, 3, topic_quotas, difficulty_quotas,
                        (), (), history, seed),
        )
        rng = random.Random(2024)
        for _ in range(10):
            shuffled_pool = list(pool)
            rng.shuffle(shuffled_pool)
            shuffled_history = [set(p) for p in history]
            rng.shuffle(shuffled_history)
            rerun = assemble(shuffled_pool, 3, topic_quotas,
                             difficulty_quotas,
                             history=shuffled_history, seed=seed)
            self.assertEqual(rerun, reference)

    def test_randomized_against_brute_force(self):
        feasible = infeasible = 0
        for trial in range(60):
            rng = random.Random(trial)
            topics = ["A", "B", "C"][: rng.randint(2, 3)]
            pool = [
                Question(f"q{i}", rng.randint(1, 3),
                         rng.sample(topics, rng.randint(1, len(topics))))
                for i in range(rng.randint(4, 8))
            ]
            count = rng.randint(1, len(pool))
            topic_quotas = {}
            for t in topics:
                lo = rng.randint(0, count)
                topic_quotas[t] = Interval(lo, rng.randint(lo, count))
            difficulty_quotas = {}
            for d in range(1, 6):
                lo = rng.randint(0, count)
                difficulty_quotas[d] = Interval(lo, rng.randint(lo, count))
            ids = [q.id for q in pool]
            required = set(rng.sample(ids, rng.randint(0, 1)))
            rest = [i for i in ids if i not in required]
            forbidden = set(rng.sample(rest, rng.randint(0, 1)))
            history = [
                set(rng.sample(ids, rng.randint(0, len(ids))))
                for _ in range(rng.randint(0, 2))
            ]
            seed = rng.randint(0, 1000)
            result = assemble(pool, count, topic_quotas, difficulty_quotas,
                              required=required, forbidden=forbidden,
                              history=history, seed=seed)
            optimum = brute_force(pool, count, topic_quotas,
                                  difficulty_quotas, required, forbidden,
                                  history, seed)
            self.assertEqual(result.ok, optimum is not None,
                             f"feasibility mismatch in trial {trial}")
            if result.ok:
                feasible += 1
                check_valid(self, result, pool, count, topic_quotas,
                            difficulty_quotas, required, forbidden)
                self.assertEqual(
                    cost_of(result.question_ids, history, seed), optimum,
                    f"cost mismatch in trial {trial}")
            else:
                infeasible += 1
        self.assertGreater(feasible, 0)
        self.assertGreater(infeasible, 0)


class TestValidationAndEdges(unittest.TestCase):
    def setUp(self):
        self.pool = [Question("q1", 1, {"A"})]
        self.tq = {"A": Interval(0, 1)}
        self.dq = full_difficulty_quotas()

    def test_empty_paper(self):
        result = assemble(self.pool, 0, self.tq, self.dq, seed=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.assignments, ())

    def test_zero_lower_bounds_still_feasible_without_questions(self):
        result = assemble([], 0, {}, self.dq, seed=0)
        self.assertTrue(result.ok)

    def test_invalid_question_rejected(self):
        with self.assertRaises(ValueError):
            Question("bad", 0, {"A"})
        with self.assertRaises(ValueError):
            Question("bad", 6, {"A"})
        with self.assertRaises(ValueError):
            Question("bad", 1, set())
        with self.assertRaises(ValueError):
            Question("", 1, {"A"})

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            Interval(2, 1)
        with self.assertRaises(ValueError):
            Interval(-1, 1)

    def test_duplicate_ids_rejected(self):
        pool = [Question("q1", 1, {"A"}), Question("q1", 2, {"A"})]
        with self.assertRaises(ValueError):
            assemble(pool, 1, self.tq, self.dq, seed=0)

    def test_required_forbidden_overlap_rejected(self):
        with self.assertRaises(ValueError):
            assemble(self.pool, 1, self.tq, self.dq,
                     required={"q1"}, forbidden={"q1"}, seed=0)

    def test_unknown_ids_rejected(self):
        with self.assertRaises(ValueError):
            assemble(self.pool, 1, self.tq, self.dq,
                     required={"nope"}, seed=0)
        with self.assertRaises(ValueError):
            assemble(self.pool, 1, self.tq, self.dq,
                     forbidden={"nope"}, seed=0)

    def test_tag_without_quota_rejected(self):
        pool = [Question("q1", 1, {"A", "B"})]
        with self.assertRaises(ValueError):
            assemble(pool, 1, self.tq, self.dq, seed=0)

    def test_difficulty_quotas_must_cover_one_to_five(self):
        with self.assertRaises(ValueError):
            assemble(self.pool, 1, self.tq, {1: Interval(0, 1)}, seed=0)

    def test_negative_seed_rejected(self):
        with self.assertRaises(ValueError):
            assemble(self.pool, 1, self.tq, self.dq, seed=-1)

    def test_tuple_quotas_accepted(self):
        result = assemble(self.pool, 1, {"A": (1, 1)},
                          {d: (0, 1) for d in range(1, 6)}, seed=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.question_ids, ("q1",))

    def test_history_ids_outside_pool_ignored(self):
        result = assemble(self.pool, 1, {"A": (1, 1)},
                          {d: (0, 1) for d in range(1, 6)},
                          history=[{"ghost"}, {"q1"}], seed=0)
        self.assertTrue(result.ok)

    def test_same_seed_same_result_different_seed_may_differ(self):
        pool = [Question(f"q{i}", 1, {"A"}) for i in range(6)]
        tq = {"A": Interval(2, 2)}
        dq = full_difficulty_quotas({1: Interval(2, 2)})
        first = assemble(pool, 2, tq, dq, seed=5)
        again = assemble(pool, 2, tq, dq, seed=5)
        self.assertEqual(first, again)
        others = {assemble(pool, 2, tq, dq, seed=s).question_ids
                  for s in range(20)}
        self.assertGreater(len(others), 1, "seed should influence choice")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
