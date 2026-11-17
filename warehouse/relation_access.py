from dataclasses import dataclass
from .bindings import BindingService
from .source_rows import load_source_rows


@dataclass(frozen=True)
class RelationRow:
    occurrence: tuple[int, int]
    values: dict


class RelationReader:
    def __init__(self, database):
        self.database = database
        self.bindings = BindingService(database)

    def iter_rows(self, binding_id, relation_name):
        relation = self.bindings.get_binding(binding_id).relation(relation_name)
        for source in load_source_rows(self.database, relation.revision_id, relation.schema):
            yield RelationRow((relation.revision_id, source.ordinal),
                              {col.identity: value for col, value in zip(relation.schema.columns, source.values)})
