"""Backlog validation (pure). Reports every problem at once, in plain language.

The LLM never fills gaps here: a missing field or unknown reference is an error, not a guess.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BacklogItem:
    key: str
    title: str
    priority: str | None
    depends_on: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)  # a valid start order (topological)
    roots: list[str] = field(default_factory=list)  # tasks that can start immediately

    @property
    def ok(self) -> bool:
        return not self.errors


VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}


def find_cycle(edges: dict[str, set[str]], nodes: list[str]) -> list[str] | None:
    """Return one dependency loop as [a, b, ..., a], or None. `edges[x]` = what x depends on."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)
    parent: dict[str, str] = {}

    for start in nodes:
        if color[start] != WHITE:
            continue
        stack = [(start, iter(sorted(edges.get(start, ()))))]
        color[start] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
            elif color.get(nxt) == GREY:
                cycle = [nxt, node]
                cur = node
                while cur != nxt:
                    cur = parent[cur]
                    cycle.append(cur)
                cycle.reverse()
                return cycle
            elif color.get(nxt) == WHITE:
                parent[nxt] = node
                color[nxt] = GREY
                stack.append((nxt, iter(sorted(edges.get(nxt, ())))))
    return None


def validate_backlog(
    items: list[BacklogItem],
    known_skills: set[str],
    team_skills: set[str],
) -> ValidationReport:
    """`known_skills`: the organization's catalog; `team_skills`: skills someone on the team has
    (both lower-case)."""
    report = ValidationReport()
    if not items:
        report.errors.append("The backlog is empty.")
        return report

    seen: set[str] = set()
    keys: list[str] = []
    for i, it in enumerate(items, start=1):
        label = it.key or f"row {i}"
        if not it.key or not it.key.strip():
            report.errors.append(f"Row {i} has no task ID.")
        elif it.key in seen:
            report.errors.append(f"Task ID {it.key} is used more than once.")
        else:
            seen.add(it.key)
            keys.append(it.key)
        if not it.title or not it.title.strip():
            report.errors.append(f"{label} has no title.")
        if it.priority is None or it.priority.upper() not in VALID_PRIORITIES:
            report.errors.append(
                f"{label} has priority {it.priority!r}; use LOW, MEDIUM, HIGH or URGENT."
            )
        for dep in it.depends_on:
            if dep == it.key:
                report.errors.append(f"{label} depends on itself.")
            elif dep not in {x.key for x in items}:
                report.errors.append(f"{label} depends on {dep}, which is not in the backlog.")
        for skill in it.required_skills:
            s = skill.strip().lower()
            if s not in known_skills:
                report.errors.append(
                    f"{label} needs skill “{skill}”, which is not in the skill catalog."
                )
            elif s not in team_skills:
                report.warnings.append(
                    f"{label} needs “{skill}”, but no one on the team has it yet — "
                    "it will need a manager decision."
                )

    if report.errors:
        return report

    edges: dict[str, set[str]] = {it.key: set(it.depends_on) for it in items}
    cycle = find_cycle(edges, keys)
    if cycle:
        report.errors.append(
            "Dependency loop: " + " → ".join(cycle) + ". Tasks in a loop can never start."
        )
        return report

    # Kahn's algorithm, deterministic by key, gives a valid start order.
    dependents: dict[str, list[str]] = defaultdict(list)
    remaining = {k: len(v) for k, v in edges.items()}
    for k, deps in edges.items():
        for d in deps:
            dependents[d].append(k)
    queue = deque(sorted(k for k, n in remaining.items() if n == 0))
    report.roots = list(queue)
    while queue:
        k = queue.popleft()
        report.order.append(k)
        for nxt in sorted(dependents[k]):
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    return report
