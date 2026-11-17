import json
import sqlite3
import tempfile
from pathlib import Path
from warehouse.database import Database
from warehouse.workflow import QualityWorkflow, quality_query, column, literal
from warehouse.result_store import ResultUnavailable
from warehouse.schemas import unpack_value
from .test_source_revisions import WarehouseCase, SAMPLES, CALIBRATIONS, query
from .test_correlation import nested_query


class TestTaskPublication(WarehouseCase):
    def exercise_publish_retry(self, binding):
        task = self.flow.tasks.create_task(binding.binding_id, quality_query())
        with self.assertRaises(ResultUnavailable):
            self.flow.reader.read_result(task)
        self.db.connection.execute(
            "CREATE TEMP TRIGGER reject_result BEFORE INSERT ON result_rows "
            "WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT,'publication failure'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.flow.tasks.run_task(task)
            self.assertEqual(self.flow.tasks.get_task(task).status, "queued")
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM result_rows WHERE task_id=?", (task,)).fetchone()[0], 0)
            with self.assertRaises(ResultUnavailable):
                self.flow.reader.read_result(task)
        finally:
            self.db.connection.execute("DROP TRIGGER reject_result")
        published = self.flow.tasks.run_task(task)
        self.assertEqual([row[0] for row in published.rows], [11, 11, 14])
        self.assertEqual(self.flow.tasks.run_task(task, 1), published)
        self.assertEqual(self.db.connection.execute(
            "SELECT COUNT(*) FROM result_rows WHERE task_id=?", (task,)).fetchone()[0], 3)
        return task

    def test_publish_retry(self):
        self.exercise_publish_retry(self.bind())

    def test_failure_retry_and_reopen(self):
        self.db.close()
        with tempfile.TemporaryDirectory(prefix="quality-reopen-") as temp:
            path = str(Path(temp) / "warehouse.sqlite")
            self.db = Database(path)
            self.flow = QualityWorkflow(self.db)
            old = self.bind()
            successful = self.exercise_publish_retry(old)
            pending = self.flow.tasks.create_task(old.binding_id, quality_query())
            old_count = self.flow.tasks.create_task(old.binding_id, quality_query(True))
            new_calibrations = CALIBRATIONS + [{"station": "B", "limit_ug_l": 50}]
            revised = self.bind(calibrations=new_calibrations, prefix="corrected")
            new_task = self.flow.tasks.create_task(revised.binding_id, quality_query())
            new_count = self.flow.tasks.create_task(revised.binding_id, quality_query(True))
            nested = self.flow.tasks.create_task(revised.binding_id, nested_query())
            saved = self.flow.reader.read_result(successful)
            self.db.close()
            self.db = Database(path)
            self.flow = QualityWorkflow(self.db)
            self.assertEqual(self.flow.reader.read_result(successful), saved)
            self.assertEqual([r[0] for r in self.flow.tasks.run_task(pending).rows], [11, 11, 14])
            self.assertEqual([r[0] for r in self.flow.tasks.run_task(new_task).rows], [11, 11, 12, 14])
            self.assertEqual(self.flow.tasks.run_task(old_count).rows, ((3,),))
            self.assertEqual(self.flow.tasks.run_task(new_count).rows, ((4,),))
            self.assertEqual(self.flow.tasks.run_task(nested, 2).rows,
                             ((11, 1), (11, 1), (12, 0), (13, 0), (14, 1)))
            self.db.close()
            self.db = Database(path)
            self.flow = QualityWorkflow(self.db)
            self.assertEqual(self.flow.reader.read_result(successful), saved)
            self.assertEqual(len(self.flow.reader.read_result(new_task).rows), 4)

    def test_export_readonly(self):
        binding = self.bind()
        document = query("samples", [
            ("id", column("sample_no")), ("measurement", column("measured_ug_l")),
            ("large", literal(2 ** 80 + 1)), ("flag", literal(True, "bool"))])
        task = self.flow.tasks.create_task(binding.binding_id, document)
        published = self.flow.tasks.run_task(task)
        def authorizer(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_READ and first in ("source_rows", "relations", "schemas"):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.db.connection.set_authorizer(authorizer)
        try:
            with tempfile.TemporaryDirectory(prefix="quality-export-") as temp:
                target = Path(temp) / "result.json"
                self.assertEqual(self.flow.reader.read_result(task, target), published)
                self.assertEqual(self.flow.tasks.run_task(task), published)
                payload = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual([c["name"] for c in payload["columns"]], ["id", "measurement", "large", "flag"])
                self.assertEqual(tuple(tuple(unpack_value(v) for v in row) for row in payload["rows"]), published.rows)
                with self.assertRaises(OSError):
                    self.flow.reader.read_result(task, Path(temp) / "missing" / "bad.json")
                self.assertEqual(self.flow.reader.read_result(task), published)
                self.assertEqual(self.flow.tasks.get_task(task).status, "succeeded")
                self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["result.json"])
        finally:
            self.db.connection.set_authorizer(None)
