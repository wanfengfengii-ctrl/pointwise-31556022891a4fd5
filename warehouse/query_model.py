from dataclasses import dataclass


class QueryError(ValueError):
    pass


@dataclass(frozen=True)
class QuerySpec:
    document: dict


@dataclass(frozen=True)
class ColumnRef:
    scope_id: str
    relation: str
    column_id: str
    name: str
    depth: int
    type: str
    nullable: bool


@dataclass(frozen=True)
class AggregateSpec:
    function: str
    argument: object = None


@dataclass(frozen=True)
class Expression:
    op: str
    type: str
    nullable: bool
    value: object = None
    ref: ColumnRef | None = None
    args: tuple = ()
    aggregate: AggregateSpec | None = None
    query: object = None


@dataclass(frozen=True)
class OutputColumn:
    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class LogicalPlan:
    binding_id: int
    scope_id: str
    relation: str
    alias: str
    column_ids: tuple[str, ...]
    select: tuple[Expression, ...]
    outputs: tuple[OutputColumn, ...]
    where: Expression | None
    group_by: tuple[Expression, ...]
    grouped: bool
    having: Expression | None
    shape: str
    document: dict


def has_aggregate(expr):
    if expr is None:
        return False
    return expr.op == "aggregate" or any(has_aggregate(arg) for arg in expr.args)
