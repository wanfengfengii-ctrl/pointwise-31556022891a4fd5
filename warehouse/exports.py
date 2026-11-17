import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from .schemas import pack_value
from .result_store import ResultStore


def export_result(result, export_path):
    path = Path(export_path)
    payload = {"version": 1, "task_id": result.task_id,
               "columns": [asdict(c) for c in result.columns],
               "rows": [[pack_value(v) for v in row] for row in result.rows]}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False) as stream:
            temporary = stream.name
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


class ResultReader:
    def __init__(self, database):
        self.results = ResultStore(database)

    def read_result(self, task_id, export_path=None):
        result = self.results.load_success(task_id)
        if export_path is not None:
            export_result(result, export_path)
        return result
