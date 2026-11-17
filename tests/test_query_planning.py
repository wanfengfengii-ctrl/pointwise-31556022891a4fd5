import copy
from warehouse.workflow import column, literal, operation, quality_query
from warehouse.query_model import QueryError
from .test_source_revisions import WarehouseCase, query


class TestQueryPlanning(WarehouseCase):
    def test_invalid_outer_reference(self):
        binding = self.bind()
        base = query("samples", [("v", column("sample_no"))])
        invalid = [
            query("samples", [("v", column("sample_no", 1))]),
            query("samples", [("v", column("missing"))]),
            query("samples", [("v", {"col": "sample_no", "relation": "wrong"})]),
            query("samples", [("v", {"agg": "sum", "expr": column("station")})]),
            query("samples", [("v", {"agg": "sum", "expr": {"agg": "count"}})]),
            query("samples", [("v", column("sample_no")), ("n", {"agg": "count"})]),
            query("samples", [("v", column("station"))], group_by=[column("sample_no")]),
            query("samples", [("v", column("station"))], having=literal(True, "bool")),
            query("samples", [("v", column("station"))], where={"agg": "count"}),
            query("samples", [("v", column("station"))], where=operation("eq", column("station"), literal(3))),
            query("samples", [("v", column("station"))], where=literal(1)),
            query("samples", [("v", literal(True))]),
            query("samples", [("v", {"agg": "sum"})]),
            query("samples", [("v", column("station"))], group_by=[{"agg": "count"}]),
            query("samples", [("v", column("station")), ("v", column("station"))]),
        ]
        multi = query("calibrations", [("a", column("station")), ("b", column("limit_ug_l"))])
        invalid.append(query("samples", [("v", {"scalar": multi})]))
        deep = base
        for _ in range(3):
            deep = query("samples", [("v", {"scalar": deep})])
        invalid.append(deep)
        outer_capture = query("calibrations", [("v", column("sample_no", 1))])
        invalid.append(query("samples", [("n", {"agg": "count"}), ("v", {"scalar": outer_capture})]))
        invalid.append(dict(copy.deepcopy(base), unknown=True))
        for document in invalid:
            before = self.counts()
            with self.assertRaises(QueryError, msg=repr(document)):
                self.flow.tasks.create_task(binding.binding_id, document)
            self.assertEqual(self.counts(), before)
        self.assertEqual(len(self.run_query(binding, quality_query())), 3)
