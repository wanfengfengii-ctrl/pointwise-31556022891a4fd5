from warehouse.workflow import column, operation, quality_query
from warehouse.subqueries import CardinalityError
from warehouse.result_store import ResultUnavailable
from .test_source_revisions import WarehouseCase, query


class TestScalarCardinality(WarehouseCase):
    def test_multiple_rows(self):
        samples = [
            {"sample_no": 1, "station": "A", "measured_ug_l": 10},
            {"sample_no": 2, "station": "B", "measured_ug_l": 10},
        ]
        calibrations = [
            {"station": "A", "limit_ug_l": 20},
            {"station": "B", "limit_ug_l": 30},
            {"station": "B", "limit_ug_l": 30},
        ]
        binding = self.bind(samples, calibrations)
        good = self.flow.tasks.create_task(binding.binding_id, quality_query())
        published = self.flow.tasks.run_task(good)
        scalar = query("calibrations", [("limit", column("limit_ug_l"))],
                       where=operation("eq", column("station"), column("station", 1)))
        document = query("samples", [("id", column("sample_no")), ("limit", {"scalar": scalar})])
        task = self.flow.tasks.create_task(binding.binding_id, document)
        for _ in range(2):
            with self.assertRaises(CardinalityError):
                self.flow.tasks.run_task(task, 1)
            self.assertEqual(self.flow.tasks.get_task(task).status, "failed")
            self.assertIn("CardinalityError", self.flow.tasks.get_task(task).error)
            self.assertEqual(self.db.connection.execute(
                "SELECT COUNT(*) FROM result_rows WHERE task_id=?", (task,)).fetchone()[0], 0)
            with self.assertRaises(ResultUnavailable):
                self.flow.reader.read_result(task)
            self.assertEqual(self.flow.reader.read_result(good), published)
        self.assertEqual(published.rows, ((1, "A", 10),))
