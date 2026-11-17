from itertools import islice
from .relation_access import RelationReader
from .frames import RowFrame, CorrelationContext
from .expressions import evaluate_expression
from .aggregates import AggregateAccumulator, group_rows
from .subqueries import evaluate_scalar_subquery


class QueryExecutor:
    def __init__(self, database):
        self.relations = RelationReader(database)

    def execute(self, plan, batch_size=128, context=None):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        context = context if context is not None else CorrelationContext()

        def recursive(subplan, subcontext):
            return self.execute(subplan, batch_size, subcontext)

        def scalar(subplan, frame, ctx):
            return evaluate_scalar_subquery(subplan, frame, ctx, recursive)

        def evaluate(expr, frame, members=None):
            def aggregate(spec):
                if members is None:
                    raise ValueError("aggregate without group")
                accumulator = AggregateAccumulator(spec.function)
                for member in members:
                    value = evaluate(spec.argument, member) if spec.argument is not None else None
                    accumulator.step(value, star=spec.argument is None)
                return accumulator.finish()
            return evaluate_expression(expr, frame, context, scalar, aggregate)

        accepted = []
        source = iter(self.relations.iter_rows(plan.binding_id, plan.relation))
        while True:
            batch = list(islice(source, batch_size))
            if not batch:
                break
            for row in batch:
                left = RowFrame(plan.scope_id, row.occurrence, row.values)
                if plan.lateral is None:
                    frames = (left,)
                else:
                    frames = self.expand(plan.lateral, left, context, batch_size)
                for frame in frames:
                    if plan.where is None or evaluate(plan.where, frame) is True:
                        accepted.append(frame)
        groups = group_rows(accepted,
                            lambda frame: tuple(evaluate(e, frame) for e in plan.group_by),
                            plan.shape)
        output = []
        for representative, members in groups:
            frame = representative if representative is not None else RowFrame(
                plan.scope_id, ("empty",), {identity: None for identity in plan.column_ids})
            if plan.having is not None and evaluate(plan.having, frame, members) is not True:
                continue
            output.append(tuple(evaluate(expr, frame, members) for expr in plan.select))
        return output

    def expand(self, lateral, left, context, batch_size=128):
        """Evaluate the right query once for this left occurrence.

        Returns combined frames carrying the left slots plus the right output
        slots, in left occurrence order then right final row order.  Null
        extension happens only after the final right relation is known.
        """
        right_rows = self.execute(lateral.plan, batch_size, context.enter(left))
        left_values = dict(left.values)
        if not right_rows:
            if lateral.mode == "inner":
                return ()
            values = dict(left_values)
            values.update((identity, None) for identity in lateral.column_ids)
            return (RowFrame(left.scope_id, (left.occurrence, ("null",)), values),)
        frames = []
        for index, row in enumerate(right_rows):
            values = dict(left_values)
            values.update(zip(lateral.column_ids, row))
            frames.append(RowFrame(left.scope_id, (left.occurrence, index), values))
        return tuple(frames)
