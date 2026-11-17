import argparse
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from .database import Database
from .sources import SourceService
from .bindings import BindingService
from .tasks import TaskService
from .exports import ResultReader


def column(name, depth=0):
    return {"col": name, "depth": depth}


def literal(value, kind="int"):
    return {"lit": value, "type": kind}


def operation(op, *args):
    return {"op": op, "args": list(args)}


def quality_query(count=False):
    match = operation("eq", column("station"), column("station", 1))
    def scalar(aggregate):
        return {"scalar": {"from": "calibrations", "as": "c",
                           "select": [{"as": "value", "expr": aggregate}], "where": match}}
    predicate = operation("and",
        operation("eq", scalar({"agg": "count"}), literal(1)),
        operation("le", column("measured_ug_l"),
                  scalar({"agg": "sum", "expr": column("limit_ug_l")})))
    select = ([{"as": "count", "expr": {"agg": "count"}}] if count else
              [{"as": name, "expr": column(name)} for name in
               ("sample_no", "station", "measured_ug_l")])
    return {"from": "samples", "as": "s", "select": select, "where": predicate}


@dataclass(frozen=True)
class DayReport:
    old_task: int
    new_task: int
    old_ids: tuple[int, ...]
    new_ids: tuple[int, ...]
    old_count: int
    new_count: int


class QualityWorkflow:
    def __init__(self, database):
        self.database = database
        self.sources = SourceService(database)
        self.bindings = BindingService(database)
        self.tasks = TaskService(database)
        self.reader = ResultReader(database)

    def bind(self, samples, calibrations):
        return self.bindings.bind_dataset(
            {"samples": samples.revision_id, "calibrations": calibrations.revision_id})

    def run_day(self, example, export_path=None):
        prefix = example["request_prefix"]
        samples = self.sources.apply_source(prefix + ":samples", "sampling", example["samples"])
        first = self.sources.apply_source(prefix + ":calibration:v1", "calibration", example["calibrations_v1"])
        old_binding = self.bind(samples, first)
        old_task = self.tasks.create_task(old_binding.binding_id, quality_query())
        old_count_task = self.tasks.create_task(old_binding.binding_id, quality_query(True))
        second = self.sources.apply_source(prefix + ":calibration:v2", "calibration", example["calibrations_v2"])
        new_binding = self.bind(samples, second)
        new_task = self.tasks.create_task(new_binding.binding_id, quality_query())
        new_count_task = self.tasks.create_task(new_binding.binding_id, quality_query(True))
        old = self.tasks.run_task(old_task)
        new = self.tasks.run_task(new_task)
        old_count = self.tasks.run_task(old_count_task).rows[0][0]
        new_count = self.tasks.run_task(new_count_task).rows[0][0]
        if old_count != len(old.rows) or new_count != len(new.rows):
            raise AssertionError("quality details and counts disagree")
        old_ids, new_ids = tuple(row[0] for row in old.rows), tuple(row[0] for row in new.rows)
        expected = example["expected"]
        if list(old_ids) != expected["old_ids"] or list(new_ids) != expected["new_ids"]:
            raise AssertionError("quality day differs from independent example")
        self.reader.read_result(new_task, export_path)
        return DayReport(old_task, new_task, old_ids, new_ids, old_count, new_count)


def main(argv=None):
    parser = argparse.ArgumentParser(description="River station quality warehouse")
    parser.add_argument("command", choices=("verify", "demo"))
    parser.add_argument("--db")
    parser.add_argument("--export")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    if args.command == "verify":
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    example = json.loads((root / "examples" / "quality_day.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="quality-demo-") as temp:
        db_path = args.db or str(Path(temp) / "warehouse.sqlite")
        export_path = args.export or str(Path(temp) / "quality.json")
        with Database(db_path) as database:
            report = QualityWorkflow(database).run_day(example, export_path)
        with Database(db_path) as database:
            old = ResultReader(database).read_result(report.old_task)
            new = ResultReader(database).read_result(report.new_task)
            if tuple(row[0] for row in old.rows) != report.old_ids or tuple(row[0] for row in new.rows) != report.new_ids:
                raise AssertionError("reopened results changed")
        evidence = {
            "case_id": "V8.snapshot_reopen", "input": example,
            "expected": example["expected"],
            "actual": {"old_ids": list(report.old_ids), "new_ids": list(report.new_ids)},
            "downstream_expected": {"old_count": 3, "new_count": 4},
            "downstream_actual": {"old_count": report.old_count, "new_count": report.new_count},
            "code_paths": ["warehouse/sources.py", "warehouse/bindings.py",
                           "warehouse/planner.py", "warehouse/executor.py",
                           "warehouse/result_store.py", "warehouse/exports.py"],
            "oracle": "hand-calculated ordered sample occurrences and independent count tasks"
        }
        print("POINTWISE_SCENARIO " + json.dumps(evidence, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
