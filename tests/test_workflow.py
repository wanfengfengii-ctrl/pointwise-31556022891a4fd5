import json
import tempfile
import unittest
from pathlib import Path
from warehouse.database import Database
from warehouse.workflow import QualityWorkflow
from warehouse.exports import ResultReader


class TestWorkflow(unittest.TestCase):
    def test_quality_day(self):
        root = Path(__file__).resolve().parent.parent
        example = json.loads((root / "examples" / "quality_day.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="quality-day-") as temp:
            path, target = Path(temp) / "data.sqlite", Path(temp) / "result.json"
            with Database(path) as db:
                workflow = QualityWorkflow(db)
                report = workflow.run_day(example, target)
                self.assertEqual(report.old_ids, (11, 11, 14))
                self.assertEqual(report.new_ids, (11, 11, 12, 14))
                self.assertEqual((report.old_count, report.new_count), (3, 4))
                revisions = db.connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]
                repeat = workflow.run_day(example, target)
                self.assertEqual(repeat.old_ids, report.old_ids)
                self.assertEqual(repeat.new_ids, report.new_ids)
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], revisions)
                self.assertEqual(revisions, 3)
            with Database(path) as db:
                self.assertEqual(len(ResultReader(db).read_result(report.old_task).rows), 3)
                self.assertEqual(len(ResultReader(db).read_result(report.new_task).rows), 4)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["rows"]), 4)
