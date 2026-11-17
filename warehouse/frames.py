from dataclasses import dataclass
from .query_model import QueryError


@dataclass(frozen=True)
class RowFrame:
    scope_id: str
    occurrence: tuple
    values: dict

    def resolve(self, ref):
        if self.scope_id != ref.scope_id or ref.column_id not in self.values:
            raise QueryError("bound column does not belong to runtime frame")
        return self.values[ref.column_id]


@dataclass(frozen=True)
class CorrelationContext:
    frames: tuple[RowFrame, ...] = ()

    def enter(self, frame):
        return CorrelationContext((frame,) + self.frames)

    def resolve_outer(self, ref):
        if not 1 <= ref.depth <= len(self.frames):
            raise QueryError("missing correlation frame")
        return self.frames[ref.depth - 1].resolve(ref)
