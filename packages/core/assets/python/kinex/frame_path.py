"""Frame edges, deterministic path selection, and lazy transform composition."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from heapq import heappop, heappush
from itertools import count

from kinex.geometry import compose_rt, invert_rt

Frame = tuple[str, str]  # device, local frame (empty for the canonical frame)
Transform = tuple[list[list[float]], list[float]]


def label(frame):
    return ":".join(part for part in frame if part)


@dataclass(frozen=True)
class Edge:
    """Child-in-parent transform; resolve=None retains an unavailable edge's reason."""

    child: Frame
    parent: Frame
    kind: str
    resolve: Callable[[], Transform] | None
    reason: str | None = None
    estimate_index: int | None = None

    @cached_property
    def transform(self):
        if self.resolve is None:
            raise ValueError(self.reason)
        return self.resolve()


def select_path(edges, child, parent):
    """Minimize (estimated links, total edges); reverse queries use the same route."""
    graph = {}
    # Ordering is independent of discovery/query direction, including parallel links.
    for edge in sorted(edges, key=lambda e: (e.child, e.parent, e.estimate_index if e.estimate_index is not None else -1)):
        if edge.resolve is None:
            continue
        graph.setdefault(edge.child, []).append((edge.parent, edge, False))
        graph.setdefault(edge.parent, []).append((edge.child, edge, True))

    source, target = sorted((child, parent))
    order = count()
    queue = [(0, 0, next(order), source)]
    costs, previous = {source: (0, 0)}, {}
    while queue:
        estimated, hops, _, node = heappop(queue)
        if costs[node] != (estimated, hops):
            continue
        if node == target:
            path = []
            while node != source:
                node, edge, inverse = previous[node]
                path.append((edge, inverse))
            if source == child:
                return list(reversed(path))
            return [(edge, not inverse) for edge, inverse in path]
        for neighbor, edge, inverse in graph.get(node, ()):
            cost = (estimated + (edge.kind == "estimated"), hops + 1)
            if neighbor in costs and costs[neighbor] <= cost:
                continue
            costs[neighbor] = cost
            previous[neighbor] = (node, edge, inverse)
            heappush(queue, (*cost, next(order), neighbor))
    return None


def compose_path(path):
    """Compose directed steps and serialize their provenance."""
    rt, used = ([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], [0., 0., 0.]), []
    for edge, inverse in path:
        rt = compose_rt(invert_rt(edge.transform) if inverse else edge.transform, rt)
        start, end = (edge.parent, edge.child) if inverse else (edge.child, edge.parent)
        entry = {"from": label(start), "to": label(end), "kind": edge.kind, "inverse": inverse}
        if edge.estimate_index is not None:
            entry["estimate_index"] = edge.estimate_index
        used.append(entry)
    return rt, used
