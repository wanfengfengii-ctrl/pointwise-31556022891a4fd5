import sqlite3
from warehouse.workflow import column, literal, operation
from warehouse.plan_codec import encode_plan, decode_plan
from warehouse.executor import QueryExecutor
from .test_source_revisions import WarehouseCase, SAMPLES, CALIBRATIONS, query


def nested_query():
    inner = query("calibrations", [("n", {"agg": "count"})],
                  where=operation("and",
                      operation("eq", column("station"), column("station", 2)),
                      operation("gt", column("limit_ug_l"), column("limit_ug_l", 1))))
    middle = query("calibrations", [("value", {"scalar": inner})],
                   where=operation("eq", column("station"), literal("B", "text")))
    return query("samples", [("id", column("sample_no")), ("n", {"scalar": middle})])


class TestCorrelation(WarehouseCase):
    def oracle(self, calibrations):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE samples(id,station,measured)")
            conn.execute("CREATE TABLE calibrations(station,lim)")
            conn.executemany("INSERT INTO samples VALUES(?,?,?)",
                             [(r["sample_no"], r["station"], r["measured_ug_l"]) for r in SAMPLES])
            conn.executemany("INSERT INTO calibrations VALUES(?,?)",
                             [(r["station"], r["limit_ug_l"]) for r in calibrations])
            return tuple(conn.execute(
                "SELECT s.id,(SELECT (SELECT COUNT(*) FROM calibrations AS inner_c "
                "WHERE inner_c.station=s.station AND inner_c.lim>middle_c.lim) "
                "FROM calibrations AS middle_c WHERE middle_c.station='B') "
                "FROM samples AS s ORDER BY s.rowid"))

    def test_two_level_scope(self):
        calibrations = CALIBRATIONS + [{"station": "B", "limit_ug_l": 50}]
        binding = self.bind(calibrations=calibrations)
        expected = self.oracle(calibrations)
        self.assertEqual(expected, ((11, 1), (11, 1), (12, 0), (13, 0), (14, 1)))
        for batch_size in (1, 2, 17):
            self.assertEqual(self.run_query(binding, nested_query(), batch_size), expected)
        _, plan = self.flow.tasks.planner.compile_query(binding.binding_id, nested_query())
        restored = decode_plan(encode_plan(plan))
        self.assertEqual(restored, plan)
        self.assertEqual(tuple(QueryExecutor(self.db).execute(restored, 2)), expected)
        null_calibrations = CALIBRATIONS + [{"station": "B", "limit_ug_l": None}]
        null_binding = self.bind(calibrations=null_calibrations, prefix="null")
        self.assertEqual(self.run_query(null_binding, nested_query()), self.oracle(null_calibrations))
        self.assertEqual(self.run_query(binding, nested_query()), expected)
