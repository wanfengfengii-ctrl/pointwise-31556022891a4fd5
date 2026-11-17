import itertools
import sqlite3
from warehouse.workflow import quality_query, column, literal, operation
from warehouse.expressions import sql_and, sql_or, sql_not
from .test_source_revisions import WarehouseCase, SAMPLES, CALIBRATIONS, query


class TestQualityFiltering(WarehouseCase):
    def test_duplicates_and_nulls(self):
        binding = self.bind()
        actual = self.run_query(binding, quality_query())
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE s(sample_no,station,measured)")
            conn.execute("CREATE TABLE c(station,lim)")
            conn.executemany("INSERT INTO s VALUES(?,?,?)",
                             [(r["sample_no"], r["station"], r["measured_ug_l"]) for r in SAMPLES])
            conn.executemany("INSERT INTO c VALUES(?,?)",
                             [(r["station"], r["limit_ug_l"]) for r in CALIBRATIONS])
            expected = tuple(conn.execute(
                "SELECT sample_no,station,measured FROM s WHERE "
                "(SELECT COUNT(*) FROM c WHERE c.station=s.station)=1 AND "
                "measured <= (SELECT SUM(lim) FROM c WHERE c.station=s.station) ORDER BY s.rowid"))
        self.assertEqual(actual, expected)
        self.assertEqual([row[0] for row in actual], [11, 11, 14])
        self.assertEqual(self.run_query(binding, quality_query(True)), ((len(actual),),))

    def test_truth_table(self):
        values = (False, True, None)
        with sqlite3.connect(":memory:") as conn:
            for left, right in itertools.product(values, repeat=2):
                expected_and, expected_or = conn.execute("SELECT ? AND ?, ? OR ?",
                                                         (left, right, left, right)).fetchone()
                self.assertEqual(sql_and(left, right), None if expected_and is None else bool(expected_and))
                self.assertEqual(sql_or(left, right), None if expected_or is None else bool(expected_or))
            for value in values:
                expected = conn.execute("SELECT NOT ?", (value,)).fetchone()[0]
                self.assertEqual(sql_not(value), None if expected is None else bool(expected))
        binding = self.bind()
        null_comparison = operation("le", column("measured_ug_l"), literal(0))
        cases = [
            (operation("not", null_comparison), [11, 11, 12, 14]),
            (operation("or", literal(True, "bool"), null_comparison), [11, 11, 12, 13, 14]),
            (operation("and", literal(False, "bool"), null_comparison), []),
        ]
        for predicate, expected in cases:
            actual = self.run_query(binding, query("samples", [("id", column("sample_no"))], where=predicate))
            self.assertEqual([row[0] for row in actual], expected)
        calibration = query("calibrations", [("station", column("station"))],
                            where=operation("not", operation("le", column("limit_ug_l"), literal(0))))
        self.assertEqual(self.run_query(binding, calibration), (("A",), ("D",)))

    def test_exact_integers(self):
        huge = 2 ** 80
        samples = [
            {"sample_no": 1, "station": "X", "measured_ug_l": 9007199254740993},
            {"sample_no": 2, "station": "Y", "measured_ug_l": huge + 1},
            {"sample_no": 3, "station": "Y", "measured_ug_l": -huge},
        ]
        binding = self.bind(samples, [{"station": "X", "limit_ug_l": 9007199254740992}], "large")
        self.assertEqual(self.run_query(binding, quality_query()), ())
        sum_y = query("samples", [("total", {"agg": "sum", "expr": column("measured_ug_l")})],
                      where=operation("eq", column("station"), literal("Y", "text")))
        self.assertEqual(self.run_query(binding, sum_y), ((1,),))
        projected = self.run_query(binding, query("samples", [("value", column("measured_ug_l"))]))
        self.assertEqual(projected, ((9007199254740993,), (huge + 1,), (-huge,)))
        enormous = 1 << 20000
        document = query("samples", [("literal", literal(enormous))])
        self.assertEqual(self.run_query(binding, document), ((enormous,),) * 3)
