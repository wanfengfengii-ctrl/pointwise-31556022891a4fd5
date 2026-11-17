from warehouse.workflow import column, literal, operation
from .test_source_revisions import WarehouseCase, SAMPLES, query


class TestEmptyAggregates(WarehouseCase):
    def test_grouping_and_having(self):
        binding = self.bind(calibrations=[])
        documents = [
            (query("calibrations", [("v", {"agg": "count"})]), ((0,),)),
            (query("calibrations", [("v", {"agg": "sum", "expr": column("limit_ug_l")})]), ((None,),)),
            (query("calibrations", [("v", {"agg": "count"})], group_by=[column("station")]), ()),
            (query("calibrations", [("v", {"agg": "count"})],
                   having=operation("gt", {"agg": "count"}, literal(0))), ()),
        ]
        for document, expected in documents:
            self.assertEqual(self.run_query(binding, document), expected)
            wrapped = query("samples", [("v", {"scalar": document})])
            value = expected[0][0] if expected else None
            self.assertEqual(self.run_query(binding, wrapped), ((value,),) * len(SAMPLES))
        count_expr = {"scalar": documents[0][0]}
        filtered = query("samples", [("id", column("sample_no"))],
                         where=operation("eq", count_expr, literal(0)))
        self.assertEqual(self.run_query(binding, filtered), ((11,), (11,), (12,), (13,), (14,)))
        empty_scalar = {"scalar": documents[3][0]}
        filtered["where"] = operation("not", operation("eq", empty_scalar, literal(0)))
        self.assertEqual(self.run_query(binding, filtered), ())

    def test_null_grouping(self):
        rows = [
            {"station": "A", "limit_ug_l": None}, {"station": "B", "limit_ug_l": 7},
            {"station": "C", "limit_ug_l": None}, {"station": "D", "limit_ug_l": 7},
            {"station": "E", "limit_ug_l": -1},
        ]
        binding = self.bind(calibrations=rows)
        document = query("calibrations", [
            ("key", column("limit_ug_l")), ("all", {"agg": "count"}),
            ("nonnull", {"agg": "count", "expr": column("limit_ug_l")}),
            ("sum", {"agg": "sum", "expr": column("limit_ug_l")})],
            group_by=[column("limit_ug_l")])
        self.assertEqual(self.run_query(binding, document),
                         ((None, 2, 0, None), (7, 2, 2, 14), (-1, 1, 1, -1)))
