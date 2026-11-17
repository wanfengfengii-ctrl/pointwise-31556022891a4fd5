from dataclasses import dataclass
from .query_model import ColumnRef, QueryError


@dataclass(frozen=True)
class ScopeColumn:
    identity: str
    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class ScopeSide:
    alias: str
    columns: tuple[ScopeColumn, ...]


@dataclass(frozen=True)
class Scope:
    """One lexical query level.

    A plain relation contributes one side.  A lateral expansion contributes a
    single scope with two sides (the original left source and the right output)
    so that combining the inputs never creates an extra lexical level.
    """

    scope_id: str
    sides: tuple[ScopeSide, ...]


@dataclass(frozen=True)
class ScopeStack:
    scopes: tuple[Scope, ...] = ()

    def push(self, scope):
        return ScopeStack((scope,) + self.scopes)

    def resolve_column(self, name, depth=0, relation=None):
        if type(depth) is not int or not 0 <= depth < len(self.scopes):
            raise QueryError("outer reference depth out of scope")
        scope = self.scopes[depth]
        if relation is not None:
            sides = [side for side in scope.sides if side.alias == relation]
            if not sides:
                raise QueryError("alias does not match declared depth")
            matches = [(side, col) for side in sides
                       for col in side.columns if col.name == name]
            if not matches:
                raise QueryError("unknown column: " + str(name))
        else:
            matches = [(side, col) for side in scope.sides
                       for col in side.columns if col.name == name]
            if not matches:
                raise QueryError("unknown column: " + str(name))
            if len(matches) != 1:
                raise QueryError("ambiguous column: " + str(name))
        side, column = matches[0]
        return ColumnRef(scope.scope_id, side.alias, column.identity, column.name,
                         depth, column.type, column.nullable)
