import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, path=":memory:"):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.initialize()

    def initialize(self):
        statements = (
            "CREATE TABLE IF NOT EXISTS metadata(version INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS schemas(name TEXT PRIMARY KEY, body TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY, dataset TEXT NOT NULL REFERENCES schemas(name), request_id TEXT UNIQUE NOT NULL, content TEXT NOT NULL, row_count INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS source_rows(revision_id INTEGER NOT NULL REFERENCES revisions(id), ordinal INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(revision_id,ordinal))",
            "CREATE TABLE IF NOT EXISTS bindings(id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS relations(binding_id INTEGER NOT NULL REFERENCES bindings(id), name TEXT NOT NULL, revision_id INTEGER NOT NULL REFERENCES revisions(id), schema_body TEXT NOT NULL, PRIMARY KEY(binding_id,name))",
            "CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, binding_id INTEGER NOT NULL REFERENCES bindings(id), plan TEXT NOT NULL, columns_body TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','succeeded','failed')), error TEXT)",
            "CREATE TABLE IF NOT EXISTS result_rows(task_id INTEGER NOT NULL REFERENCES tasks(id), ordinal INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(task_id,ordinal))",
        )
        with self.transaction():
            for statement in statements:
                self.connection.execute(statement)
            versions = self.connection.execute("SELECT version FROM metadata").fetchall()
            if not versions:
                self.connection.execute("INSERT INTO metadata VALUES(1)")
            elif len(versions) != 1 or versions[0][0] != 1:
                raise ValueError("unsupported database version")

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError("nested transaction")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
