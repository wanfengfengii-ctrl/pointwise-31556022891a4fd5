"""Regression checks for the lateral representation and planning interface.

These complement lateral_examples.LateralChecks: they pin the frozen plan
representation, lexical depth, input ownership and nullable widening.
"""
import copy
import unittest

from warehouse.database import Database
from warehouse.workflow import QualityWorkflow
from warehouse.query_model import QueryError
from warehouse.plan_codec import encode_plan, decode_plan
from warehouse.executor import QueryExecutor
from lateral_examples import SAMPLES, CALIBRATIONS, col, lit, op, query, candidates, bind


class TestLateralRepresentation(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.flow = QualityWorkflow(self.db)
        self.binding = bind(self.flow)

    def tearDown(self):
        self.db.close()

    def compile(self, document, binding=None):
        binding = binding or self.binding
        return self.flow.tasks.planner.compile_query(binding.binding_id, document)[1]

    def run_query(self, document, binding=None, batch_size=7):
        binding = binding or self.binding
        task = self.flow.tasks.create_task(binding.binding_id, document)
        return self.flow.tasks.run_task(task, batch_size).rows

    def test_plan_freezes_both_sides(self):
        plan = self.compile(candidates())
        self.assertEqual(plan.alias, "s")
        self.assertEqual(plan.lateral.alias, "r")
        self.assertEqual(plan.lateral.mode, "left")
        self.assertEqual([c.name for c in plan.lateral.plan.outputs],
                         ["station", "limit_ug_l"])
        # Right slots never collide with the left source identities, even when
        # both sides read the same bound relation.
        left_ids = set(plan.column_ids) - set(plan.lateral.column_ids)
        self.assertEqual(left_ids, {"sampling.sample_no", "sampling.station", "sampling.measured"})
        self.assertTrue(all(identity.startswith(plan.scope_id + ":r:")
                            for identity in plan.lateral.column_ids))
        restored = decode_plan(encode_plan(plan))
        self.assertEqual(restored, plan)
        self.assertEqual(encode_plan(restored), encode_plan(plan))
        self.assertEqual(tuple(QueryExecutor(self.db).execute(restored, 1)),
                         self.run_query(candidates()))

    def test_unqualified_rules_after_expansion(self):
        # A name unique to one side resolves unqualified after expansion.
        document = query("samples", "s", [
            ("id", col("sample_no", "s")), ("lim", col("limit_ug_l"))],
            lateral={"as": "r", "mode": "left", "query": query(
                "calibrations", "c", [("limit_ug_l", col("limit_ug_l", "c"))],
                where=op("eq", col("station", "c"), col("station", "s", 1)))})
        self.assertEqual(self.run_query(document),
                         ((11, 100), (11, 120), (11, 100), (11, 120), (12, None), (13, None)))
        # A name present on both sides is ambiguous, not silently preferred.
        ambiguous = query("samples", "s", [("v", col("station"))],
                          lateral={"as": "r", "mode": "left",
                                   "query": query("calibrations", "c", [("station", col("station"))])})
        with self.assertRaises(QueryError):
            self.compile(ambiguous)
        # An unselected right source column is not exposed through the alias.
        hidden = query("calibrations", "c", [("limit_ug_l", col("limit_ug_l", "c"))])
        hidden["select"] = [{"as": "limit_ug_l", "expr": col("limit_ug_l", "c")}]
        visible = query("samples", "s", [("v", col("station", "r"))],
                        lateral={"as": "r", "mode": "left", "query": hidden})
        with self.assertRaises(QueryError):
            self.compile(visible)

    def test_nullable_widening_does_not_touch_right_semantics(self):
        same_source = bind(self.flow, [SAMPLES[0], dict(SAMPLES[0], sample_no=15)],
                           CALIBRATIONS, "same-source")
        inner = query("samples", "s", [
            ("left_id", col("sample_no", "s")), ("right_id", col("sample_no", "r"))],
            lateral={"as": "r", "mode": "inner", "query": query(
                "samples", "other", [("sample_no", col("sample_no", "other"))],
                where=op("eq", col("station", "other"), col("station", "s", 1)))})
        left = copy.deepcopy(inner)
        left["lateral"]["mode"] = "left"
        inner_plan = self.compile(inner, same_source)
        left_plan = self.compile(left, same_source)
        self.assertFalse(inner_plan.outputs[1].nullable)
        self.assertTrue(left_plan.outputs[1].nullable)
        self.assertEqual(inner_plan.outputs[0].nullable, left_plan.outputs[0].nullable)
        self.assertEqual(self.run_query(inner, same_source),
                         ((11, 11), (11, 15), (15, 11), (15, 15)))

    def test_grouped_right_keeps_internal_types(self):
        document = query("samples", "s", [("n", col("n", "r"))],
                         lateral={"as": "r", "mode": "left", "query": query(
                             "calibrations", "c", [("n", {"agg": "count"})],
                             where=op("eq", col("station", "c"), col("station", "s", 1)))})
        plan = self.compile(document)
        self.assertTrue(plan.outputs[0].nullable)
        self.assertFalse(plan.lateral.plan.outputs[0].nullable)
        self.assertEqual(self.run_query(document), ((2,), (2,), (0,), (1,)))

    def test_depth_and_shadowing(self):
        # A right-query local alias may shadow the left alias; explicit depth
        # still selects the intended scope.
        shadow = query("samples", "s", [("v", col("station", "s")), ("n", col("n", "r"))],
                       lateral={"as": "r", "mode": "inner",
                                "query": query("samples", "s", [("n", {"agg": "count"})])})
        self.assertEqual(self.run_query(shadow), (("A", 4), ("A", 4), ("B", 4), ("C", 4)))
        # A scalar inside the right query reaches its own source at depth 1 and
        # the original left row at depth 2.
        document = query("samples", "s", [("id", col("sample_no", "s")), ("v", col("v", "r"))],
                         lateral={"as": "r", "mode": "inner", "query": query(
                             "calibrations", "c", [
                                 ("v", {"scalar": query(
                                     "samples", "p", [("n", {"agg": "count"})],
                                     where=op("and",
                                              op("eq", col("station", "p"), col("station", "c", 1)),
                                              op("eq", col("station", "p"), col("station", "s", 2))))})],
                             where=op("eq", col("station", "c"), col("station", "s", 1)))})
        self.assertEqual(self.run_query(document), ((11, 2), (11, 2), (11, 2), (11, 2), (13, 1)))
        # Depth beyond the available scopes is rejected, not inferred.
        bad = query("samples", "s", [("v", col("station", "s", 2))],
                    lateral={"as": "r", "mode": "left",
                             "query": query("calibrations", "c", [("k", col("station", "c"))])})
        with self.assertRaises(QueryError):
            self.compile(bad)

    def test_lateral_only_at_root_and_alias_parts(self):
        root = candidates()
        scalar_wrap = query("samples", "s", [("v", {"scalar": copy.deepcopy(root)})])
        with self.assertRaises(QueryError):
            self.compile(scalar_wrap)
        nested = copy.deepcopy(root)
        nested["lateral"]["query"]["lateral"] = copy.deepcopy(nested["lateral"])
        with self.assertRaises(QueryError):
            self.compile(nested)
        for mutate in (lambda d: d["lateral"].pop("mode"),
                       lambda d: d["lateral"].__setitem__("extra", 1),
                       lambda d: d["lateral"].__setitem__("mode", "outer"),
                       lambda d: d["lateral"].__setitem__("as", "s"),
                       lambda d: d["lateral"].__setitem__("as", "bad name"),
                       lambda d: d.__setitem__("group_by", []),
                       lambda d: d.__setitem__("having", lit(True, "bool"))):
            document = copy.deepcopy(root)
            mutate(document)
            before = self.db.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            with self.assertRaises(QueryError):
                self.compile(document)
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM tasks").fetchone()[0], before)

    def test_occurrence_order_and_duplicate_expansion(self):
        rows = self.run_query(candidates(), batch_size=1)
        self.assertEqual([row[0] for row in rows], [11, 11, 11, 11, 12, 13])
        self.assertEqual(rows[:4], ((11, "A", "A", 100), (11, "A", "A", 120)) * 2)
        # A top-level filter applies after expansion.
        filtered = candidates()
        filtered["where"] = op("eq", col("limit_ug_l", "r"), lit(120))
        self.assertEqual(self.run_query(filtered), ((11, "A", "A", 120), (11, "A", "A", 120)))
        # Global aggregation counts combined rows, including expanded duplicates.
        counted = copy.deepcopy(filtered)
        counted.pop("where")
        counted["select"] = [{"as": "n", "expr": {"agg": "count"}}]
        self.assertEqual(self.run_query(counted), ((6,),))


if __name__ == "__main__":
    unittest.main()
