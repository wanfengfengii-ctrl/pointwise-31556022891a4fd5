from .query_model import QueryError, has_aggregate
from .schemas import valid_name, value_matches


def validate_query_json(query, level=0, allow_lateral=False):
    if level > 2 or type(query) is not dict:
        raise QueryError("query must be an object; at most two nested scalar levels")
    allowed = {"from", "as", "select", "where", "group_by", "having"}
    if allow_lateral and level == 0:
        allowed = allowed | {"lateral"}
    if set(query) - allowed or not {"from", "as", "select"} <= set(query):
        raise QueryError("invalid query fields")
    if not valid_name(query["from"]) or not valid_name(query["as"]):
        raise QueryError("invalid relation or alias")
    if type(query["select"]) is not list or not query["select"]:
        raise QueryError("select must be a nonempty ordered list")
    names = set()
    for output in query["select"]:
        if type(output) is not dict or set(output) != {"as", "expr"}:
            raise QueryError("invalid select item")
        if not valid_name(output["as"]) or output["as"] in names:
            raise QueryError("output names must be unique")
        names.add(output["as"])
    if "group_by" in query and type(query["group_by"]) is not list:
        raise QueryError("group_by must be a list")
    if "lateral" in query:
        _validate_lateral_shape(query)
    return query


def _validate_lateral_shape(query):
    if "group_by" in query or "having" in query:
        raise QueryError("a lateral top-level query may not group or filter groups")
    lateral = query["lateral"]
    if type(lateral) is not dict or set(lateral) != {"as", "mode", "query"}:
        raise QueryError("lateral requires exactly as, mode and query")
    if not valid_name(lateral["as"]):
        raise QueryError("invalid lateral alias")
    if lateral["as"] == query["as"]:
        raise QueryError("lateral alias must differ from the top-level alias")
    if lateral["mode"] not in ("inner", "left"):
        raise QueryError("lateral mode must be inner or left")
    if type(lateral["query"]) is not dict:
        raise QueryError("lateral query must be an object")


def validate_expression_types(op, args):
    if op in ("and", "or"):
        if len(args) != 2 or any(arg.type != "bool" for arg in args):
            raise QueryError("boolean binary operator requires two booleans")
        return "bool", any(arg.nullable for arg in args)
    if op == "not":
        if len(args) != 1 or args[0].type != "bool":
            raise QueryError("not requires one boolean")
        return "bool", args[0].nullable
    if op in ("eq", "ne", "lt", "le", "gt", "ge"):
        if len(args) != 2 or args[0].type != args[1].type:
            raise QueryError("comparison requires two values of the same type")
        return "bool", any(arg.nullable for arg in args)
    raise QueryError("unknown expression operator")


def validate_literal(kind, value):
    if kind not in ("int", "text", "bool") or not value_matches(value, kind, True):
        raise QueryError("literal requires an explicit scalar type")
    return kind, value is None


def _outer_refs(plan, nesting=1):
    expressions = (*plan.select, *plan.group_by, plan.where, plan.having)
    for expr in expressions:
        if expr is None:
            continue
        yield from _refs_in_expr(expr, nesting)


def _refs_in_expr(expr, nesting):
    if expr.op == "column" and expr.ref.depth == nesting:
        yield expr.ref
    for arg in expr.args:
        yield from _refs_in_expr(arg, nesting)
    if expr.aggregate and expr.aggregate.argument is not None:
        yield from _refs_in_expr(expr.aggregate.argument, nesting)
    if expr.query is not None:
        yield from _outer_refs(expr.query, nesting + 1)


def validate_aggregate_usage(select, where, groups, grouped, having, shape):
    if has_aggregate(where) or any(has_aggregate(g) for g in groups):
        raise QueryError("aggregate in WHERE or GROUP BY")
    if having is not None and shape == "projection":
        raise QueryError("HAVING requires grouping or an aggregate")
    if shape == "projection":
        return
    directly_grouped = {g.ref.column_id for g in groups if g.op == "column" and g.ref.depth == 0}

    def check(expr):
        if expr is None or expr.op == "aggregate" or expr in groups:
            return
        if expr.op == "column" and expr.ref.depth == 0:
            if expr.ref.column_id not in directly_grouped:
                raise QueryError("ungrouped current column")
        for arg in expr.args:
            check(arg)
        if expr.query is not None:
            for ref in _outer_refs(expr.query):
                if ref.column_id not in directly_grouped:
                    raise QueryError("subquery captures ungrouped current column")
    for expression in (*select, having):
        check(expression)
