import operator


def sql_compare(op, left, right):
    if left is None or right is None:
        return None
    operations = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
                  "le": operator.le, "gt": operator.gt, "ge": operator.ge}
    return operations[op](left, right)


def sql_and(left, right):
    if left is False or right is False:
        return False
    return None if left is None or right is None else True


def sql_or(left, right):
    if left is True or right is True:
        return True
    return None if left is None or right is None else False


def sql_not(value):
    return None if value is None else not value


def evaluate_expression(expr, frame, context, scalar, aggregate):
    if expr.op == "literal":
        return expr.value
    if expr.op == "column":
        return frame.resolve(expr.ref) if expr.ref.depth == 0 else context.resolve_outer(expr.ref)
    if expr.op == "scalar":
        return scalar(expr.query, frame, context)
    if expr.op == "aggregate":
        return aggregate(expr.aggregate)
    values = [evaluate_expression(arg, frame, context, scalar, aggregate) for arg in expr.args]
    if expr.op == "and":
        return sql_and(*values)
    if expr.op == "or":
        return sql_or(*values)
    if expr.op == "not":
        return sql_not(*values)
    return sql_compare(expr.op, *values)
