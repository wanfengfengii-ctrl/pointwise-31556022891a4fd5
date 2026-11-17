from .schemas import schema_text, schema_from_text, BUILTIN_SCHEMAS, BindingError


class Catalog:
    def __init__(self, database):
        self.database = database
        for schema in BUILTIN_SCHEMAS:
            self.ensure_schema(schema)

    def ensure_schema(self, schema):
        body = schema_text(schema)
        with self.database.transaction() as conn:
            row = conn.execute("SELECT body FROM schemas WHERE name=?", (schema.name,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO schemas VALUES(?,?)", (schema.name, body))
            elif row["body"] != body:
                raise BindingError("incompatible schema: " + schema.name)
        return schema

    def get_schema(self, name):
        row = self.database.connection.execute("SELECT body FROM schemas WHERE name=?", (name,)).fetchone()
        if row is None:
            raise BindingError("unknown dataset: " + str(name))
        return schema_from_text(row["body"])
