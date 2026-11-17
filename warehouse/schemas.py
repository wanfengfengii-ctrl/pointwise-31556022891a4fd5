import json
import re
from dataclasses import dataclass, asdict


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class ColumnSchema:
    identity: str
    name: str
    type: str
    nullable: bool = False


@dataclass(frozen=True)
class DatasetSchema:
    name: str
    columns: tuple[ColumnSchema, ...]


SAMPLING_SCHEMA = DatasetSchema("sampling", (
    ColumnSchema("sampling.sample_no", "sample_no", "int"),
    ColumnSchema("sampling.station", "station", "text"),
    ColumnSchema("sampling.measured", "measured_ug_l", "int", True),
))
CALIBRATION_SCHEMA = DatasetSchema("calibration", (
    ColumnSchema("calibration.station", "station", "text"),
    ColumnSchema("calibration.limit", "limit_ug_l", "int", True),
))
BUILTIN_SCHEMAS = (SAMPLING_SCHEMA, CALIBRATION_SCHEMA)


def valid_name(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None


def validate_schema(schema):
    if not isinstance(schema, DatasetSchema) or not valid_name(schema.name) or not schema.columns:
        raise BindingError("invalid schema")
    names, identities = set(), set()
    for col in schema.columns:
        if not isinstance(col, ColumnSchema) or not valid_name(col.name):
            raise BindingError("invalid column")
        if not col.identity or col.identity in identities or col.name in names:
            raise BindingError("duplicate column identity or name")
        if col.type not in ("int", "text", "bool") or type(col.nullable) is not bool:
            raise BindingError("invalid column type")
        names.add(col.name)
        identities.add(col.identity)
    return schema


def schema_text(schema):
    validate_schema(schema)
    return json.dumps(asdict(schema), sort_keys=True, separators=(",", ":"))


def schema_from_text(body):
    data = json.loads(body)
    return validate_schema(DatasetSchema(data["name"], tuple(ColumnSchema(**c) for c in data["columns"])))


def pack_value(value):
    if type(value) is int:
        return {"integer_hex": hex(value)}
    if value is None or type(value) in (str, bool):
        return value
    raise ValueError("unsupported scalar value")


def unpack_value(value):
    if type(value) is dict and set(value) == {"integer_hex"}:
        return int(value["integer_hex"], 16)
    if value is None or type(value) in (str, bool):
        return value
    raise ValueError("invalid encoded scalar")


def value_matches(value, kind, nullable):
    if value is None:
        return nullable
    return type(value) is {"int": int, "text": str, "bool": bool}.get(kind)
