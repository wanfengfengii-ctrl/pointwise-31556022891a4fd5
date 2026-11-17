import json
from .schemas import pack_value, unpack_value, value_matches


def validate_result_row(columns, row):
    if not isinstance(row, (tuple, list)) or len(row) != len(columns):
        raise ValueError("result width does not match output columns")
    for column, value in zip(columns, row):
        if not value_matches(value, column.type, column.nullable):
            raise ValueError("result type mismatch: " + column.name)
    return tuple(row)


def encode_result_row(columns, row):
    values = validate_result_row(columns, row)
    return json.dumps([pack_value(v) for v in values], ensure_ascii=True, separators=(",", ":"))


def decode_result_row(columns, body):
    values = tuple(unpack_value(v) for v in json.loads(body))
    return validate_result_row(columns, values)
