"""Deterministic intent parser for spoken commands (no LLM). Pure and fully testable.

Phase 6 covers navigation and read-only questions. Phrases that would CHANGE data are
recognised as `change.not_yet` so the assistant can say so honestly (Phase 7 adds them with
confirmation through the execution harness).
"""

import re
from dataclasses import dataclass, field

_FILLER = re.compile(
    r"^(?:(?:hey|hi|ok|okay)\s+voice\s*flow[,.]?\s*)?"
    r"(?:(?:please|can you|could you|would you|i want to|i would like to|i'd like to|let's|lets)\s+)*",
)
_TRAILING = re.compile(r"\s*(?:please|for me|now|thanks|thank you)$")

_TAB_WORDS = {
    "team": "team",
    "people": "team",
    "members": "team",
    "task": "tasks",
    "tasks": "tasks",
    "backlog": "tasks",
    "overview": "overview",
    "summary": "overview",
}
_NAV = r"(?:open|show|show me|go to|goto|take me to|navigate to|switch to|display|view|see)"


@dataclass(frozen=True)
class Intent:
    name: str
    slots: dict[str, str] = field(default_factory=dict)


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("’", "'").replace("e commerce", "ecommerce").replace("e-commerce", "ecommerce")
    t = re.sub(r"[^\w\s']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _FILLER.sub("", t)
    t = _TRAILING.sub("", t).strip()
    return t


def _m(pattern: str, text: str) -> re.Match | None:
    return re.fullmatch(pattern, text)


def parse(text: str) -> Intent:
    t = normalize(text)
    if not t:
        return Intent("empty")

    # --- control words -------------------------------------------------------------
    if _m(r"(?:stop|cancel|never mind|nevermind|forget it|be quiet|quiet)", t):
        return Intent("cancel")
    if _m(r"(?:repeat|say (?:that|it) again|what did you say|pardon|sorry)", t):
        return Intent("repeat")
    if _m(r"(?:help|what can i say|what can you do|commands)", t):
        return Intent("help")

    # --- things that change data: recognised, but not available by voice yet ------
    if re.search(
        r"\b(?:i(?:'ve| have)? (?:completed|finished|done)|i am done|i'm done|mark (?:it |this )?"
        r"(?:as )?(?:done|complete)|approve|reject|assign|reassign|a signed|"  # "a signed" = misheard "assign"
        r"i'm blocked|i am blocked|"
        r"blocked|start (?:the |my )?(?:task|project|work)|decline|cancel (?:the )?task|"
        r"extend|extension|more time)\b",
        t,
    ):
        return Intent("change.not_yet", {"utterance": t})

    # --- read-only questions --------------------------------------------------------
    if _m(
        r"(?:what(?:'s| is)|tell me) my (?:current |next )?task|what should i (?:do|work on)(?: now| next)?|"
        r"what am i (?:doing|working on)|what do i (?:have to|need to) do(?: now| today)?",
        t,
    ):
        return Intent("query.my_task")
    if _m(
        r"(?:read|check|any|do i have any|what are) (?:my |new |the )*notifications?|"
        r"what(?:'s| is) new|any updates",
        t,
    ):
        return Intent("query.notifications")
    if m := _m(
        r"(?:what(?:'s| is) (?:still )?pending|what(?:'s| is) left|project status|status of (?:the )?(.+?)(?: project)?|"
        r"how(?:'s| is) (?:the )?(.+?)(?: project)? (?:going|doing))",
        t,
    ):
        name = next((g for g in m.groups() if g), None)
        return Intent("query.pending", {"project": name} if name else {})
    if _m(
        r"(?:read|describe) (?:this|the) (?:page|screen)|what(?:'s| is) on (?:the |this )?(?:page|screen)|where am i",
        t,
    ):
        return Intent("read_page")

    # --- navigation -----------------------------------------------------------------
    if _m(r"(?:go )?back|go to (?:the )?previous page", t):
        return Intent("nav.back")
    if _m(r"(?:go )?home|(?:go to|open) (?:the )?(?:home|start) (?:page|screen)", t):
        return Intent("nav.home")
    if _m(rf"(?:{_NAV} )?(?:my (?:work|tasks|task list)|work)", t):
        return Intent("nav.my_work")
    if _m(rf"(?:{_NAV} )?(?:my |the )?notifications?(?: page)?", t):
        return Intent("nav.notifications")
    if _m(rf"(?:{_NAV} )?(?:the )?system status(?: page)?", t):
        return Intent("nav.system")
    if _m(rf"(?:{_NAV} )?(?:all |my |the )*projects(?: page| list)?", t):
        return Intent("nav.projects")
    if _m(rf"(?:{_NAV} )?(?:the |my )?team(?: page)?", t):
        return Intent("nav.team")

    # "show the project team", "show tasks", "show the overview" (current project)
    if m := _m(
        rf"(?:{_NAV} )?(?:the )?(?:project )?(team|people|members|tasks|task|backlog|overview|summary)",
        t,
    ):
        return Intent("nav.project_tab", {"tab": _TAB_WORDS[m.group(1)]})

    # "open the ecommerce project", "show the ecommerce team", "go to mobile banking tasks"
    if m := _m(
        rf"{_NAV} (?:the )?(.+?)(?: project)?(?:'s)?(?: (team|people|members|tasks|backlog|overview))?",
        t,
    ):
        query, tab = m.group(1).strip(), m.group(2)
        if query and query not in {"page", "screen", "it", "that", "this"}:
            slots = {"project": query}
            if tab:
                slots["tab"] = _TAB_WORDS[tab]
            return Intent("nav.project", slots)

    return Intent("unknown", {"utterance": t})
