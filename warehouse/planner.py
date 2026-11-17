import copy
from .bindings import BindingService
from .schemas import BindingError
from .query_model import (QueryError, QuerySpec, Expression, AggregateSpec,
                          OutputColumn, LogicalPlan, has_aggregate)
from .query_validation import (validate_query_json, validate_expression_types,
                               validate_literal, validate_aggregate_usage)
from .scopes import ScopeStack


class QueryPlanner:
    def __init__(self, database):
        self.bindings = BindingService(database)

    def compile_query(self, binding_id, query_json):
        try:
            binding = self.bindings.get_binding(binding_id)
        except BindingError as exc:
            raise QueryError(str(exc)) from exc
        document = copy.deepcopy(query_json)
        serial = iter(range(1000000))

        def compile_level(query, parents, level):
            validate_query_json(query, level)
            try:
                relation = binding.relation(query["from"])
            except BindingError as exc:
                raise QueryError(str(exc)) from exc
            scope_id = "q" + str(next(serial))
            scopes = parents.push(scope_id, query["as"], relation.schema)

            def expression(node, allow_aggregate=True, in_aggregate=False):
                if type(node) is not dict:
                    raise QueryError("expression must be an object")
                if set(node) == {"lit", "type"}:
                    kind, nullable = validate_literal(node["type"], node["lit"])
                    return Expression("literal", kind, nullable, value=node["lit"])
                if "col" in node and set(node) <= {"col", "depth", "relation"}:
                    ref = scopes.resolve_column(node["col"], node.get("depth", 0), node.get("relation"))
                    return Expression("column", ref.type, ref.nullable, ref=ref)
                if set(node) == {"scalar"}:
                    subplan = compile_level(node["scalar"], scopes, level + 1)
                    if len(subplan.outputs) != 1:
                        raise QueryError("scalar query must select exactly one column")
                    return Expression("scalar", subplan.outputs[0].type, True, query=subplan)
                if "agg" in node and set(node) <= {"agg", "expr"}:
                    if not allow_aggregate or in_aggregate:
                        raise QueryError("illegal aggregate position or nesting")
                    function = node["agg"]
                    if function not in ("count", "sum"):
                        raise QueryError("unsupported aggregate")
                    if function == "sum" and "expr" not in node:
                        raise QueryError("SUM requires an integer expression")
                    argument = expression(node["expr"], False, True) if "expr" in node else None
                    if function == "sum" and argument.type != "int":
                        raise QueryError("SUM requires integers")
                    return Expression("aggregate", "int", function == "sum",
                                      aggregate=AggregateSpec(function, argument))
                if set(node) == {"op", "args"} and type(node["args"]) is list:
                    args = tuple(expression(a, allow_aggregate, in_aggregate) for a in node["args"])
                    kind, nullable = validate_expression_types(node["op"], args)
                    return Expression(node["op"], kind, nullable, args=args)
                raise QueryError("invalid expression fields")

            select = tuple(expression(item["expr"]) for item in query["select"])
            where = expression(query["where"], False) if "where" in query else None
            groups = tuple(expression(node, False) for node in query.get("group_by", []))
            having = expression(query["having"]) if "having" in query else None
            for predicate in (where, having):
                if predicate is not None and predicate.type != "bool":
                    raise QueryError("predicate must be boolean")
            grouped = "group_by" in query
            shape = "grouped" if grouped else (
                "global" if any(has_aggregate(e) for e in (*select, having)) else "projection")
            validate_aggregate_usage(select, where, groups, grouped, having, shape)
            outputs = tuple(OutputColumn(item["as"], expr.type, expr.nullable)
                            for item, expr in zip(query["select"], select))
            return LogicalPlan(binding.binding_id, scope_id, relation.name, query["as"],
                               tuple(c.identity for c in relation.schema.columns), select,
                               outputs, where, groups, grouped, having, shape, query)
        plan = compile_level(document, ScopeStack(), 0)
        return QuerySpec(document), plan
