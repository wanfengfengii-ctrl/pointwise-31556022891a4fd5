"""Public examples and checks for ordered correlated relation expansion.

This file supplies queries, ordinary business expectations and verification only.
The V1 engine intentionally has no lateral implementation.
"""
import argparse
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from warehouse.database import Database
from warehouse.workflow import QualityWorkflow
from warehouse.query_model import QueryError
from warehouse.plan_codec import encode_plan, decode_plan
from warehouse.executor import QueryExecutor
from warehouse.subqueries import CardinalityError
from warehouse.result_store import ResultUnavailable

SAMPLES = [
    {"sample_no": 11, "station": "A", "measured_ug_l": 80},
    {"sample_no": 11, "station": "A", "measured_ug_l": 80},
    {"sample_no": 12, "station": "B", "measured_ug_l": 40},
    {"sample_no": 13, "station": "C", "measured_ug_l": None},
]
CALIBRATIONS = [
    {"station": "A", "limit_ug_l": 100},
    {"station": "A", "limit_ug_l": 120},
    {"station": "C", "limit_ug_l": None},
]
EXPECTED = (
    (11, "A", "A", 100), (11, "A", "A", 120),
    (11, "A", "A", 100), (11, "A", "A", 120),
    (12, "B", None, None), (13, "C", "C", None),
)


def col(name, relation=None, depth=0):
    value = {"col": name, "depth": depth}
    if relation is not None:
        value["relation"] = relation
    return value


def lit(value, kind="int"):
    return {"lit": value, "type": kind}


def op(name, *args):
    return {"op": name, "args": list(args)}


def query(source, alias, outputs, **clauses):
    return {"from": source, "as": alias,
            "select": [{"as": name, "expr": expr} for name, expr in outputs],
            **clauses}


def candidates(mode="left"):
    right = query("calibrations", "c", [
        ("station", col("station", "c")),
        ("limit_ug_l", col("limit_ug_l", "c"))],
        where=op("eq", col("station", "c"), col("station", "s", 1)))
    return query("samples", "s", [
        ("sample_no", col("sample_no", "s")),
        ("left_station", col("station", "s")),
        ("right_station", col("station", "r")),
        ("limit", col("limit_ug_l", "r"))],
        lateral={"as": "r", "mode": mode, "query": right})


def bind(flow, samples=SAMPLES, calibrations=CALIBRATIONS, prefix="lateral"):
    s = flow.sources.apply_source(prefix + ":s", "sampling", samples)
    c = flow.sources.apply_source(prefix + ":c", "calibration", calibrations)
    return flow.bind(s, c)


class LateralChecks(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.flow = QualityWorkflow(self.db)
        self.binding = bind(self.flow)

    def tearDown(self):
        self.db.close()

    def run_query(self, document, binding=None, batch_size=1):
        binding = binding or self.binding
        task = self.flow.tasks.create_task(binding.binding_id, document)
        return self.flow.tasks.run_task(task, batch_size)

    def test_order_types_and_roundtrip(self):
        for size in (1, 2, 17):
            self.assertEqual(self.run_query(candidates(), batch_size=size).rows, EXPECTED)
            expected_inner = tuple(row for row in EXPECTED if row[1] != "B")
            self.assertEqual(self.run_query(candidates("inner"), batch_size=size).rows,
                             expected_inner)
        _, plan = self.flow.tasks.planner.compile_query(self.binding.binding_id, candidates())
        restored = decode_plan(encode_plan(plan))
        self.assertEqual(encode_plan(restored), encode_plan(plan))
        self.assertEqual(tuple(QueryExecutor(self.db).execute(restored)), EXPECTED)
        self.assertEqual([(c.name, c.type, c.nullable) for c in plan.outputs], [
            ("sample_no", "int", False), ("left_station", "text", False),
            ("right_station", "text", True), ("limit", "int", True)])
        _, inner = self.flow.tasks.planner.compile_query(self.binding.binding_id, candidates("inner"))
        self.assertFalse(inner.outputs[2].nullable)
        document = candidates()
        document["where"] = op("gt", col("limit_ug_l", "r"), lit(110))
        self.assertEqual(self.run_query(document).rows, (EXPECTED[1], EXPECTED[3]))

    def test_final_empty_shapes(self):
        binding = bind(self.flow, [SAMPLES[2]], [], "empty")
        right = query("calibrations", "c", [("n", {"agg": "count"})],
                      where=op("eq", col("station", "c"), col("station", "s", 1)))
        document = query("samples", "s", [("n", col("n", "r"))],
                         lateral={"as": "r", "mode": "left", "query": right})
        self.assertEqual(self.run_query(document, binding).rows, ((0,),))
        grouped = copy.deepcopy(document)
        grouped["lateral"]["query"]["group_by"] = [col("station", "c")]
        self.assertEqual(self.run_query(grouped, binding).rows, ((None,),))
        having = copy.deepcopy(document)
        having["lateral"]["query"]["having"] = op("gt", {"agg": "count"}, lit(0))
        self.assertEqual(self.run_query(having, binding).rows, ((None,),))
        for variant, expected in ((document, ((0,),)), (grouped, ()), (having, ())):
            variant = copy.deepcopy(variant)
            variant["lateral"]["mode"] = "inner"
            self.assertEqual(self.run_query(variant, binding).rows, expected)
        total = candidates()
        total["select"] = [{"as": "n", "expr": {"agg": "count"}}]
        self.assertEqual(self.run_query(total).rows, ((6,),))

    def test_both_correlation_environments(self):
        document = candidates()
        for side, expected in (("s", (2, 2, 2, 2, 1, 1)),
                               ("r", (2, 2, 2, 2, 0, 1))):
            scalar = query("samples", "probe", [("n", {"agg": "count"})],
                           where=op("eq", col("station", "probe"), col("station", side, 1)))
            document["select"].append({"as": "matched", "expr": {"scalar": scalar}})
            self.assertEqual(tuple(row[-1] for row in self.run_query(document).rows), expected)
            document["select"].pop()
        deep = query("samples", "probe", [("n", {"agg": "count"})],
                     where=op("and",
                         op("eq", col("station", "probe"), col("station", "c", 1)),
                         op("eq", col("station", "probe"), col("station", "s", 2))))
        document["lateral"]["query"]["select"].append(
            {"as": "matched", "expr": {"scalar": deep}})
        document["select"].append({"as": "matched", "expr": col("matched", "r")})
        self.assertEqual(tuple(row[-1] for row in self.run_query(document).rows),
                         (2, 2, 2, 2, None, 1))

    def test_same_source_identities(self):
        document = query("samples", "s", [
            ("left_id", col("sample_no", "s")), ("right_id", col("sample_no", "r"))],
            lateral={"as": "r", "mode": "inner", "query":
                query("samples", "other", [("sample_no", col("sample_no", "other"))],
                      where=op("eq", col("station", "other"), col("station", "s", 1)))})
        binding = bind(self.flow, [SAMPLES[0], dict(SAMPLES[0], sample_no=15)],
                       CALIBRATIONS, "same-source")
        self.assertEqual(self.run_query(document, binding).rows,
                         ((11, 11), (11, 15), (15, 11), (15, 15)))

    def test_invalid_scope_and_shape(self):
        invalid = []
        document = candidates()
        document["select"][1]["expr"] = col("station")
        invalid.append(document)
        document = candidates()
        document["lateral"]["as"] = "s"
        invalid.append(document)
        document = candidates()
        document["lateral"]["query"]["where"] = op(
            "eq", col("station", "c"), col("station", "r", 1))
        invalid.append(document)
        document = candidates()
        document["select"].append({"as": "bad", "expr": {"scalar":
            query("samples", "probe", [("v", col("station", depth=1))])}})
        invalid.append(document)
        document = candidates()
        document["group_by"] = []
        invalid.append(document)
        document = candidates()
        document["lateral"]["mode"] = "outer"
        invalid.append(document)
        document = candidates()
        document["lateral"]["query"]["lateral"] = copy.deepcopy(document["lateral"])
        invalid.append(document)
        invalid.append(query("samples", "s", [("v", {"scalar": candidates()})]))
        for document in invalid:
            before = self.db.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            with self.assertRaises(QueryError):
                self.flow.tasks.create_task(self.binding.binding_id, document)
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM tasks").fetchone()[0], before)

    def test_late_scalar_error_and_publish_retry(self):
        # The first two left occurrences succeed; B then has a multi-row scalar.
        document = candidates()
        scalar = query("calibrations", "probe", [("v", col("limit_ug_l", "probe"))],
                       where=op("ne", col("station", "probe"), col("station", "s", 1)))
        document["select"].append({"as": "scalar", "expr": {"scalar": scalar}})
        task = self.flow.tasks.create_task(self.binding.binding_id, document)
        for _ in range(2):
            with self.assertRaises(CardinalityError):
                self.flow.tasks.run_task(task, 1)
            self.assertEqual(self.flow.tasks.get_task(task).status, "failed")
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM result_rows WHERE task_id=?", (task,)).fetchone()[0], 0)
            with self.assertRaises(ResultUnavailable):
                self.flow.reader.read_result(task)
        task = self.flow.tasks.create_task(self.binding.binding_id, candidates())
        self.db.connection.execute(
            "CREATE TEMP TRIGGER stop_lateral BEFORE INSERT ON result_rows "
            "WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT,'publication interrupted'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.flow.tasks.run_task(task)
            self.assertEqual(self.flow.tasks.get_task(task).status, "queued")
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM result_rows WHERE task_id=?", (task,)).fetchone()[0], 0)
        finally:
            self.db.connection.execute("DROP TRIGGER stop_lateral")
        self.assertEqual(self.flow.tasks.run_task(task).rows, EXPECTED)

    def test_frozen_reopen(self):
        report = demo()
        self.assertEqual(report["old"], [list(row) for row in EXPECTED])
        self.assertEqual(report["new"][-2], [12, "B", "B", 50])


def demo():
    with tempfile.TemporaryDirectory(prefix="lateral-demo-") as directory:
        path = Path(directory) / "warehouse.sqlite"
        with Database(path) as db:
            flow = QualityWorkflow(db)
            old_binding = bind(flow)
            document = candidates()
            old_task = flow.tasks.create_task(old_binding.binding_id, document)
            # Caller-owned JSON and a later source revision must not rebind old_task.
            document["lateral"]["mode"] = "inner"
            new_binding = bind(flow, calibrations=CALIBRATIONS + [
                {"station": "B", "limit_ug_l": 50}], prefix="revised")
            new_task = flow.tasks.create_task(new_binding.binding_id, candidates())
        with Database(path) as db:
            flow = QualityWorkflow(db)
            old = flow.tasks.run_task(old_task, 1)
            new = flow.tasks.run_task(new_task, 2)
            if old.rows != EXPECTED:
                raise AssertionError("old queued task lost its frozen expansion")
            expected_new = EXPECTED[:4] + ((12, "B", "B", 50), EXPECTED[-1])
            if new.rows != expected_new:
                raise AssertionError("new calibration did not expand")
            flow.reader.read_result(old_task, Path(directory) / "old.json")
        with Database(path) as db:
            reader = QualityWorkflow(db).reader
            if reader.read_result(old_task) != old or reader.read_result(new_task) != new:
                raise AssertionError("saved expansion changed after reopening")
        return {"old": [list(row) for row in old.rows],
                "new": [list(row) for row in new.rows]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "demo", "fixtures"))
    command = parser.parse_args(argv).command
    if command == "fixtures":
        print(json.dumps({"samples": SAMPLES, "calibrations": CALIBRATIONS,
                          "query": candidates(), "expected": EXPECTED}, ensure_ascii=False))
        return 0
    if command == "demo":
        print("POINTWISE_SCENARIO " + json.dumps(demo(), ensure_ascii=False))
        return 0
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(LateralChecks))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
