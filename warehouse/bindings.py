from dataclasses import dataclass
from .catalog import Catalog
from .revisions import RevisionRepository
from .validation import InputError
from .schemas import BindingError, DatasetSchema, valid_name, schema_text, schema_from_text


@dataclass(frozen=True)
class RelationBinding:
    name: str
    revision_id: int
    schema: DatasetSchema


@dataclass(frozen=True)
class DatasetBinding:
    binding_id: int
    relations: tuple[RelationBinding, ...]

    def relation(self, name):
        for relation in self.relations:
            if relation.name == name:
                return relation
        raise BindingError("unknown relation: " + str(name))


class BindingService:
    def __init__(self, database):
        self.database = database
        self.catalog = Catalog(database)
        self.revisions = RevisionRepository(database)

    def bind_dataset(self, relations):
        if type(relations) is not dict or not relations:
            raise BindingError("relations must be a nonempty mapping")
        resolved = []
        for name, revision_id in relations.items():
            if not valid_name(name) or type(revision_id) is not int:
                raise BindingError("invalid relation declaration")
            try:
                receipt = self.revisions.read_revision(revision_id)
            except InputError as exc:
                raise BindingError(str(exc)) from exc
            resolved.append(RelationBinding(name, revision_id, self.catalog.get_schema(receipt.dataset)))
        with self.database.transaction() as conn:
            binding_id = conn.execute("INSERT INTO bindings DEFAULT VALUES").lastrowid
            for relation in resolved:
                conn.execute("INSERT INTO relations VALUES(?,?,?,?)",
                             (binding_id, relation.name, relation.revision_id, schema_text(relation.schema)))
        return DatasetBinding(binding_id, tuple(resolved))

    def get_binding(self, binding_id):
        if type(binding_id) is not int:
            raise BindingError("invalid binding id")
        if self.database.connection.execute("SELECT 1 FROM bindings WHERE id=?", (binding_id,)).fetchone() is None:
            raise BindingError("unknown binding")
        rows = self.database.connection.execute(
            "SELECT * FROM relations WHERE binding_id=? ORDER BY rowid", (binding_id,))
        return DatasetBinding(binding_id, tuple(RelationBinding(
            row["name"], row["revision_id"], schema_from_text(row["schema_body"])) for row in rows))
