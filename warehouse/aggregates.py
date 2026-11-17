from dataclasses import dataclass


@dataclass
class AggregateAccumulator:
    function: str
    count: int = 0
    total: int = 0

    def step(self, value=None, star=False):
        if star or value is not None:
            self.count += 1
            if self.function == "sum":
                if type(value) is not int:
                    raise TypeError("SUM input must be integer")
                self.total += value

    def finish(self):
        if self.function == "count":
            return self.count
        if self.function == "sum":
            return self.total if self.count else None
        raise ValueError("unknown aggregate function")


def group_rows(rows, key, shape):
    if shape == "projection":
        return [(row, [row]) for row in rows]
    if shape == "global":
        return [(rows[0] if rows else None, rows)]
    groups = {}
    for row in rows:
        group_key = key(row)
        groups.setdefault(group_key, []).append(row)
    return [(members[0], members) for members in groups.values()]
