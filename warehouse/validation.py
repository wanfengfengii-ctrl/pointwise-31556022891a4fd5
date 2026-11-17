from .schemas import value_matches


class InputError(ValueError):
    pass


def validate_source_request(request_id, dataset):
    if type(request_id) is not str or not request_id.strip():
        raise InputError("request_id must be nonempty text")
    if dataset not in ("sampling", "calibration"):
        raise InputError("unknown source dataset")


def validate_source_rows(schema, rows):
    if not isinstance(rows, (list, tuple)):
        raise InputError("rows must be an ordered list")
    names = {c.name for c in schema.columns}
    normalized = []
    for ordinal, row in enumerate(rows):
        if type(row) is not dict or set(row) != names:
            raise InputError(f"row {ordinal}: fields must exactly match schema")
        ordered = {}
        for col in schema.columns:
            value = row[col.name]
            if not value_matches(value, col.type, col.nullable):
                raise InputError(f"row {ordinal}: invalid {col.name}")
            ordered[col.name] = value
        normalized.append(ordered)
    return tuple(normalized)
