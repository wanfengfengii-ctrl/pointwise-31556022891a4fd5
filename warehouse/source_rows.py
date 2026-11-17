import json
from dataclasses import dataclass
from .schemas import pack_value, unpack_value, value_matches


@dataclass(frozen=True)
class SourceRow:
    ordinal: int
    values: tuple


def encode_source_row(schema, row):
    return json.dumps([pack_value(row[c.name]) for c in schema.columns],
                      ensure_ascii=True, separators=(",", ":"))


def decode_source_row(schema, body):
    values = tuple(unpack_value(v) for v in json.loads(body))
    if len(values) != len(schema.columns):
        raise ValueError("source row width mismatch")
    for col, value in zip(schema.columns, values):
        if not value_matches(value, col.type, col.nullable):
            raise ValueError("source row type mismatch")
    return values


def store_source_rows(conn, revision_id, bodies):
    conn.executemany("INSERT INTO source_rows VALUES(?,?,?)",
                     ((revision_id, i, body) for i, body in enumerate(bodies)))


def load_source_rows(database, revision_id, schema):
    cursor = database.connection.execute(
        "SELECT ordinal,body FROM source_rows WHERE revision_id=? ORDER BY ordinal", (revision_id,))
    for expected, row in enumerate(cursor):
        if row["ordinal"] != expected:
            raise ValueError("noncontiguous source rows")
        yield SourceRow(expected, decode_source_row(schema, row["body"]))
