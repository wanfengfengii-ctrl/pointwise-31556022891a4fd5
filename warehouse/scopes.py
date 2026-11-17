from dataclasses import dataclass
from .query_model import ColumnRef, QueryError


@dataclass(frozen=True)
class Scope:
    scope_id: str
    alias: str
    schema: object


@dataclass(frozen=True)
class ScopeStack:
    scopes: tuple[Scope, ...] = ()

    def push(self, scope_id, alias, schema):
        return ScopeStack((Scope(scope_id, alias, schema),) + self.scopes)

    def resolve_column(self, name, depth=0, relation=None):
        if type(depth) is not int or not 0 <= depth < len(self.scopes):
            raise QueryError("outer reference depth out of scope")
        scope = self.scopes[depth]
        if relation is not None and relation != scope.alias:
            raise QueryError("alias does not match declared depth")
        for col in scope.schema.columns:
            if col.name == name:
                return ColumnRef(scope.scope_id, scope.alias, col.identity, col.name,
                                 depth, col.type, col.nullable)
        raise QueryError("unknown column: " + str(name))
