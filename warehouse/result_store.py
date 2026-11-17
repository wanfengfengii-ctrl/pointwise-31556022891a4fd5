import json
from dataclasses import dataclass, asdict
from .query_model import OutputColumn
from .result_codec import encode_result_row, decode_result_row


class ResultUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class TaskRecord:
    task_id: int
    binding_id: int
    plan: str
    columns: tuple[OutputColumn, ...]
    status: str
    error: str | None


@dataclass(frozen=True)
class PublishedResult:
    task_id: int
    columns: tuple[OutputColumn, ...]
    rows: tuple[tuple, ...]


class ResultStore:
    def __init__(self, database):
        self.database = database

    def create_queued(self, binding_id, plan, columns):
        body = json.dumps([asdict(c) for c in columns], sort_keys=True, separators=(",", ":"))
        with self.database.transaction() as conn:
            task_id = conn.execute(
                "INSERT INTO tasks(binding_id,plan,columns_body,status) VALUES(?,?,?,'queued')",
                (binding_id, plan, body)).lastrowid
        return task_id

    def load_task(self, task_id):
        row = self.database.connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ResultUnavailable("unknown task")
        return TaskRecord(row["id"], row["binding_id"], row["plan"],
                          tuple(OutputColumn(**c) for c in json.loads(row["columns_body"])),
                          row["status"], row["error"])

    def mark_failed(self, task_id, message):
        with self.database.transaction() as conn:
            record = self.load_task(task_id)
            if record.status != "queued":
                raise RuntimeError("only queued tasks can fail")
            conn.execute("UPDATE tasks SET status='failed',error=? WHERE id=?", (message, task_id))

    def publish_success(self, task_id, rows):
        record = self.load_task(task_id)
        bodies = tuple(encode_result_row(record.columns, row) for row in rows)
        with self.database.transaction() as conn:
            if self.load_task(task_id).status != "queued":
                raise RuntimeError("only queued tasks can publish")
            for ordinal, body in enumerate(bodies):
                conn.execute("INSERT INTO result_rows VALUES(?,?,?)", (task_id, ordinal, body))
            conn.execute("UPDATE tasks SET status='succeeded',error=NULL WHERE id=?", (task_id,))
        return self.load_success(task_id)

    def load_success(self, task_id):
        record = self.load_task(task_id)
        if record.status != "succeeded":
            raise ResultUnavailable("task has no published result: " + record.status)
        cursor = self.database.connection.execute(
            "SELECT ordinal,body FROM result_rows WHERE task_id=? ORDER BY ordinal", (task_id,))
        rows = []
        for expected, row in enumerate(cursor):
            if row["ordinal"] != expected:
                raise ValueError("noncontiguous result sequence")
            rows.append(decode_result_row(record.columns, row["body"]))
        return PublishedResult(task_id, record.columns, tuple(rows))
