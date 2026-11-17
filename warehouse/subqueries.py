class CardinalityError(ValueError):
    pass


def scalar_from_rows(rows):
    iterator = iter(rows)
    first = next(iterator, None)
    if first is None:
        return None
    if len(first) != 1:
        raise CardinalityError("scalar query has more than one column")
    if next(iterator, None) is not None:
        raise CardinalityError("scalar query returned multiple rows")
    return first[0]


def evaluate_scalar_subquery(plan, frame, context, execute):
    return scalar_from_rows(execute(plan, context.enter(frame)))
