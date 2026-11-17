import json
from dataclasses import asdict
from .query_model import (LogicalPlan, LateralPlan, Expression, ColumnRef,
                          AggregateSpec, OutputColumn, QueryError)
from .schemas import pack_value, unpack_value


def _pack_tree(value):
    if type(value) is int:
        return pack_value(value)
    if type(value) in (list, tuple):
        return [_pack_tree(v) for v in value]
    if type(value) is dict:
        return {key: _pack_tree(v) for key, v in value.items()}
    return value


def _unpack_tree(value):
    if type(value) is dict:
        if set(value) == {"integer_hex"}:
            return unpack_value(value)
        return {key: _unpack_tree(v) for key, v in value.items()}
    if type(value) is list:
        return [_unpack_tree(v) for v in value]
    return value


def _strip_null_lateral(value):
    """Drop structural ``lateral: null`` members anywhere in a plan tree.

    asdict recurses through scalar subplans as well, so the cleanup must too.
    Persisted V1 plans predate the member and must stay byte-identical.
    """
    if type(value) is dict:
        return {key: _strip_null_lateral(v) for key, v in value.items()
                if not (key == "lateral" and v is None)}
    if type(value) in (list, tuple):
        return [_strip_null_lateral(v) for v in value]
    return value


def encode_plan(plan):
    return json.dumps({"version": 1, "plan": _pack_tree(_strip_null_lateral(asdict(plan)))},
                      ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def decode_plan(body):
    def expression(data):
        if data is None:
            return None
        data = dict(data)
        data["args"] = tuple(expression(arg) for arg in data["args"])
        data["ref"] = ColumnRef(**data["ref"]) if data["ref"] is not None else None
        if data["aggregate"] is not None:
            aggregate = data["aggregate"]
            data["aggregate"] = AggregateSpec(aggregate["function"], expression(aggregate["argument"]))
        data["query"] = plan(data["query"]) if data["query"] is not None else None
        return Expression(**data)

    def lateral(data):
        if data is None:
            return None
        data = dict(data)
        data["outputs"] = tuple(OutputColumn(**c) for c in data["outputs"])
        data["column_ids"] = tuple(data["column_ids"])
        data["plan"] = plan(data["plan"])
        return LateralPlan(**data)

    def plan(data):
        data = dict(data)
        for key in ("select", "group_by"):
            data[key] = tuple(expression(e) for e in data[key])
        data["where"] = expression(data["where"])
        data["having"] = expression(data["having"])
        data["outputs"] = tuple(OutputColumn(**c) for c in data["outputs"])
        data["column_ids"] = tuple(data["column_ids"])
        data["lateral"] = lateral(data.get("lateral"))
        if data["shape"] not in ("projection", "global", "grouped"):
            raise QueryError("invalid plan shape")
        return LogicalPlan(**data)
    try:
        envelope = json.loads(body)
        if set(envelope) != {"version", "plan"} or envelope["version"] != 1:
            raise QueryError("unsupported plan representation")
        result = plan(_unpack_tree(envelope["plan"]))
        if encode_plan(result) != body:
            raise QueryError("noncanonical or incomplete plan")
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise QueryError("invalid stored plan: " + str(exc)) from exc
