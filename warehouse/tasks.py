from .planner import QueryPlanner
from .plan_codec import encode_plan, decode_plan
from .executor import QueryExecutor
from .subqueries import CardinalityError
from .result_store import ResultStore


class TaskService:
    def __init__(self, database):
        self.planner = QueryPlanner(database)
        self.executor = QueryExecutor(database)
        self.results = ResultStore(database)

    def create_task(self, binding_id, query_json):
        _, plan = self.planner.compile_query(binding_id, query_json)
        return self.results.create_queued(binding_id, encode_plan(plan), plan.outputs)

    def get_task(self, task_id):
        return self.results.load_task(task_id)

    def run_task(self, task_id, batch_size=128):
        record = self.results.load_task(task_id)
        if record.status == "succeeded":
            return self.results.load_success(task_id)
        if record.status == "failed":
            raise CardinalityError(record.error)
        plan = decode_plan(record.plan)
        if plan.binding_id != record.binding_id or plan.outputs != record.columns:
            raise ValueError("task and plan disagree")
        try:
            rows = self.executor.execute(plan, batch_size)
        except CardinalityError as exc:
            self.results.mark_failed(task_id, "CardinalityError: " + str(exc))
            raise
        return self.results.publish_success(task_id, rows)
