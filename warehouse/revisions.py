import json
from dataclasses import dataclass
from .schemas import schema_text
from .source_rows import store_source_rows, encode_source_row
from .validation import InputError


@dataclass(frozen=True)
class RevisionReceipt:
    revision_id: int
    request_id: str
    dataset: str
    row_count: int


class RevisionRepository:
    def __init__(self, database):
        self.database = database

    def read_request(self, request_id):
        row = self.database.connection.execute(
            "SELECT * FROM revisions WHERE request_id=?", (request_id,)).fetchone()
        return None if row is None else self._receipt(row)

    def read_revision(self, revision_id):
        row = self.database.connection.execute(
            "SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if row is None:
            raise InputError("unknown revision")
        return self._receipt(row)

    @staticmethod
    def _receipt(row):
        return RevisionReceipt(row["id"], row["request_id"], row["dataset"], row["row_count"])

    def commit_revision(self, request_id, schema, rows):
        bodies = tuple(encode_source_row(schema, row) for row in rows)
        content = json.dumps([schema_text(schema), bodies], ensure_ascii=True, separators=(",", ":"))
        with self.database.transaction() as conn:
            previous = conn.execute("SELECT * FROM revisions WHERE request_id=?", (request_id,)).fetchone()
            if previous is not None:
                if previous["content"] != content or previous["dataset"] != schema.name:
                    raise InputError("request_id already used for different ordered content")
                return self._receipt(previous)
            cur = conn.execute(
                "INSERT INTO revisions(dataset,request_id,content,row_count) VALUES(?,?,?,?)",
                (schema.name, request_id, content, len(bodies)))
            revision_id = cur.lastrowid
            store_source_rows(conn, revision_id, bodies)
        return RevisionReceipt(revision_id, request_id, schema.name, len(bodies))
