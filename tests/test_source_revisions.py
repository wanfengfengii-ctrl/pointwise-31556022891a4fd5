import unittest
from warehouse.database import Database
from warehouse.workflow import QualityWorkflow, column, literal, operation
from warehouse.validation import InputError
from warehouse.schemas import (BindingError, DatasetSchema, ColumnSchema, SAMPLING_SCHEMA)
from warehouse.catalog import Catalog
from warehouse.relation_access import RelationReader


SAMPLES = [
    {"sample_no": 11, "station": "A", "measured_ug_l": 80},
    {"sample_no": 11, "station": "A", "measured_ug_l": 80},
    {"sample_no": 12, "station": "B", "measured_ug_l": 40},
    {"sample_no": 13, "station": "C", "measured_ug_l": None},
    {"sample_no": 14, "station": "D", "measured_ug_l": 9007199254740993},
]
CALIBRATIONS = [
    {"station": "A", "limit_ug_l": 100},
    {"station": "C", "limit_ug_l": None},
    {"station": "D", "limit_ug_l": 9007199254740994},
]


def query(relation, select, **clauses):
    return {"from": relation, "as": relation[0],
            "select": [{"as": name, "expr": expr} for name, expr in select], **clauses}


class WarehouseCase(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.flow = QualityWorkflow(self.db)

    def tearDown(self):
        self.db.close()

    def bind(self, samples=SAMPLES, calibrations=CALIBRATIONS, prefix="fixture"):
        source = self.flow.sources.apply_source(prefix + ":s", "sampling", samples)
        calibration = self.flow.sources.apply_source(prefix + ":c", "calibration", calibrations)
        return self.flow.bind(source, calibration)

    def run_query(self, binding, document, batch_size=128):
        task = self.flow.tasks.create_task(binding.binding_id, document)
        return self.flow.tasks.run_task(task, batch_size).rows

    def counts(self):
        return tuple(self.db.connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                     for table in ("revisions", "source_rows", "bindings", "relations", "tasks", "result_rows"))


class TestSourceRevisions(WarehouseCase):
    def test_apply_and_bind(self):
        old = self.bind()
        revised = CALIBRATIONS + [{"station": "B", "limit_ug_l": 50}]
        new = self.bind(calibrations=revised, prefix="new")
        reader = RelationReader(self.db)
        self.assertEqual(len(list(reader.iter_rows(old.binding_id, "calibrations"))), 3)
        self.assertEqual(len(list(reader.iter_rows(new.binding_id, "calibrations"))), 4)
        before = self.counts()
        self.db.initialize()
        QualityWorkflow(self.db)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.flow.bindings.get_binding(old.binding_id), old)
        task = self.flow.tasks.create_task(old.binding_id, query("samples", [("id", column("sample_no"))]))
        self.flow.tasks.run_task(task)
        saved = self.flow.reader.read_result(task)
        self.db.initialize()
        self.assertEqual(QualityWorkflow(self.db).reader.read_result(task), saved)
        self.assertEqual(Catalog(self.db).get_schema("sampling"), SAMPLING_SCHEMA)
        with self.assertRaises(BindingError):
            Catalog(self.db).ensure_schema(DatasetSchema("sampling", (ColumnSchema("other", "x", "text"),)))
        self.assertEqual(Catalog(self.db).get_schema("sampling"), SAMPLING_SCHEMA)

    def test_request_conflict(self):
        rows = [SAMPLES[0], SAMPLES[2]]
        receipt = self.flow.sources.apply_source("request", "sampling", rows)
        reordered_keys = [dict(reversed(list(row.items()))) for row in rows]
        self.assertEqual(self.flow.sources.apply_source("request", "sampling", reordered_keys), receipt)
        before = self.counts()
        changes = [list(reversed(rows)), [dict(rows[0], measured_ug_l=81), rows[1]], rows + [rows[0]]]
        for changed in changes:
            with self.assertRaises(InputError):
                self.flow.sources.apply_source("request", "sampling", changed)
            self.assertEqual(self.counts(), before)
        with self.assertRaises(InputError):
            self.flow.sources.apply_source("request", "calibration", CALIBRATIONS)
        self.assertEqual(self.counts(), before)

    def test_invalid_batch_atomicity(self):
        self.bind()
        for index, bad in enumerate((True, 1.5, "80")):
            before = self.counts()
            rows = [SAMPLES[0], dict(SAMPLES[2], measured_ug_l=bad)]
            request = "invalid:" + str(index)
            with self.assertRaises(InputError):
                self.flow.sources.apply_source(request, "sampling", rows)
            self.assertEqual(self.counts(), before)
            self.assertIsNone(self.flow.sources.revisions.read_request(request))
            good = self.flow.sources.apply_source(request, "sampling", [SAMPLES[0], SAMPLES[2]])
            self.assertEqual(good.row_count, 2)
        for malformed in ({"sample_no": 1, "station": "A"}, dict(SAMPLES[0], extra=1)):
            before = self.counts()
            with self.assertRaises(InputError):
                self.flow.sources.apply_source("fields", "sampling", [malformed])
            self.assertEqual(self.counts(), before)

    def test_binding_rejection(self):
        valid = self.bind()
        revision = valid.relations[0].revision_id
        before = self.counts()
        with self.assertRaises(BindingError):
            self.flow.bindings.bind_dataset({"samples": revision, "calibrations": 999999})
        self.assertEqual(self.counts(), before)
        same = self.flow.bindings.bind_dataset({"left": revision, "right": revision})
        self.assertEqual(same.relations[0].revision_id, same.relations[1].revision_id)
        for mapping in ({}, {"bad name": revision}, {"samples": True}):
            before = self.counts()
            with self.assertRaises(BindingError):
                self.flow.bindings.bind_dataset(mapping)
            self.assertEqual(self.counts(), before)
