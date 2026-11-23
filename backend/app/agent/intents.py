"""Deterministic intent parser for spoken commands (no LLM). Pure and fully testable.

Navigation and read-only questions are answered directly. Commands that CHANGE data become
`task.*` / `project.*` intents with slots; the execution harness resolves them against the
database, asks for anything missing, reads them back and waits for "yes" before acting.
Unsupported changes (deadline extensions, declining) remain `change.not_yet`.
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

# Spoken percentages: "sixty", "sixty five", "a hundred" (used only before "percent").
_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_PCT_WORDS = (
    r"(?:a |one )?hundred|(?:"
    + "|".join(_TENS)
    + r")(?:[ -](?:"
    + "|".join(_UNITS)
    + r"))?|"
    + "|".join(_TEENS)
    + "|"
    + "|".join(_UNITS)
)


def _percent_words(word: str) -> int | None:
    parts = word.replace("-", " ").split()
    if parts[-1] == "hundred":
        return 100
    if len(parts) == 1:
        return _TENS.get(parts[0]) or _TEENS.get(parts[0]) or _UNITS.get(parts[0])
    if parts[0] in _TENS and parts[1] in _UNITS:
        return _TENS[parts[0]] + _UNITS[parts[1]]
    return None


@dataclass(frozen=True)
class Intent:
    name: str
    slots: dict[str, str] = field(default_factory=dict)


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("’", "'").replace("e commerce", "ecommerce").replace("e-commerce", "ecommerce")
    t = re.sub(r"[^\w\s']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\ba signed\b", "assign", t)  # common mishearing of "assign"
    t = re.sub(r"^a sign\b", "assign", t)  # "A sign X to Y" (only as the first words)
    t = _FILLER.sub("", t)
    t = _TRAILING.sub("", t).strip()
    return t


def _m(pattern: str, text: str) -> re.Match | None:
    return re.fullmatch(pattern, text)


_PRONOUN = {
    "",
    "it",
    "this",
    "that",
    "my task",
    "the task",
    "this task",
    "that task",
    "task",
    "my work",
    "work",
}


def _task_hint(s: str | None) -> str:
    """'the product listing page task' -> 'product listing page'; pronouns -> ''."""
    s = (s or "").strip()
    s = re.sub(r"^(?:the|my|our)\s+", "", s)
    s = re.sub(r"\s+task$", "", s).strip()
    return "" if s in _PRONOUN else s


def _raw_after(raw: str, words: str) -> str | None:
    """Text after 'because' / 'note' in the ORIGINAL words (keeps capitals and punctuation)."""
    m = re.search(rf"\b(?:{words})\b[\s:,-]*(.+)$", raw, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip().rstrip(".") if m and m.group(1).strip() else None


def _change_intent(t: str, raw: str) -> Intent | None:
    """Commands that change data. Returns None if `t` is not one."""
    if _m(
        r"(?:(?:yes|yeah|yep|please|sure|okay|ok|go ahead|do it|confirm|confirmed|correct|that's right|right)\s*)+",
        t,
    ):
        return Intent("confirm.yes")
    if _m(r"(?:(?:no|nope|no thanks|don't|do not|wait|not now|not|don't do it)\s*)+", t):
        return Intent("confirm.no")

    note = _raw_after(raw, r"note|notes|with the note|with a note|note is")
    reason = _raw_after(raw, r"because|since|reason is|due to")
    body = re.split(
        r"\b(?:because|since|reason is|due to|note|notes|with the note|with a note)\b", t
    )[0].strip()

    # Manager: decide an extension request (before generic approve/reject)
    if m := _m(
        r"(?:approved?|accept(?:ed)?|grant(?:ed)?|allow(?:ed)?) (?:the |that |this )?(?:deadline |time )?extension(?: request)?(?: (?:for|on) (?:the )?(.+))?",
        body,
    ):
        return Intent("extension.approve", {"task": _task_hint(m.group(1))})
    if m := _m(
        r"(?:deny|reject|decline|refuse) (?:the |that |this )?(?:deadline |time )?extension(?: request)?(?: (?:for|on) (?:the )?(.+))?",
        body,
    ):
        slots = {"task": _task_hint(m.group(1))}
        if reason:
            slots["reason"] = reason
        return Intent("extension.deny", slots)

    # Employee: decline an assignment
    if m := _m(
        r"(?:i can't do|i cannot do|i can not do|i won't be able to do|i'm not able to do|i am not able to do|i (?:want to |would like to |have to )?decline|decline)(.*)",
        body,
    ):
        slots = {"task": _task_hint(m.group(1))}
        if reason:
            slots["reason"] = reason
        return Intent("task.decline", slots)

    # Employee: ask for more time (the date words stay in "when" for the date parser)
    if re.search(
        r"\b(?:more time|extra time|an? (?:deadline )?extension|extend (?:the |my )?(?:deadline|due date)|more days?|more weeks?|another (?:day|week))\b",
        body,
    ):
        hint = ""
        if m := re.search(
            r"\b(?:on|for|with|of) (?:the |my )?(.+?)(?= until| till| by| to | in \d| in (?:a|one|two|three|four|five) | for (?:\w+ )?(?:more |extra )?(?:days?|weeks?)\b|$)",
            body,
        ):
            hint = _task_hint(m.group(1))
            if re.fullmatch(
                r"(?:\w+ )?(?:more |extra )?(?:days?|weeks?)|(?:a|one|another) (?:day|week)", hint
            ):
                hint = ""
        slots = {"task": hint, "when": body}
        if reason:
            slots["reason"] = reason
        return Intent("task.extend", slots)

    # Employee: progress ("I'm about 60 percent done with the catalog API")
    if m := _m(
        r"(?:i'm|i am|it's|it is|we're|we are|progress (?:on (?:the )?(.+?) )?is)? ?(?:about |around |roughly |nearly |almost |at )?"
        rf"(\d{{1,3}}|{_PCT_WORDS}|half|halfway|a quarter|quarter|three quarters)( percent| per cent)?(?: done| complete| finished| through| of the way)?(?: (?:with|on) (?:the |my )?(.+))?",
        body,
    ):
        word = m.group(2)
        percent = {
            "half": 50,
            "halfway": 50,
            "a quarter": 25,
            "quarter": 25,
            "three quarters": 75,
        }.get(word)
        if percent is None and word.isdigit():
            percent = int(word)
        if percent is None and m.group(3):  # number words count only with "percent"
            percent = _percent_words(word)
        if percent is not None and percent <= 100 and (word.isdigit() or m.group(0) != word):
            return Intent(
                "task.progress",
                {"task": _task_hint(m.group(1) or m.group(4)), "percent": str(percent)},
            )

    # Employee: completion
    # "mark as complete", "mark it done", "set this as completed" -> the current task
    if _m(
        r"(?:mark|set)(?: (?:it|this|that|my task|the task|this task|that task|my work))?(?: as)? (?:done|complete|completed|finished)",
        body,
    ):
        return Intent("task.complete", {"task": "", **({"note": note} if note else {})})
    # "complete my task", "finish it", "complete website testing"
    if m := _m(r"(?:complete|finish)(?: (.+))?", body):
        return Intent(
            "task.complete", {"task": _task_hint(m.group(1)), **({"note": note} if note else {})}
        )
    if m := _m(
        r"(?:i(?:'ve| have)? (?:completed|finished)|i(?:'m| am) (?:done|finished) with|i(?:'m| am) done|i finished|"
        r"(?:mark|set) )(.*?)(?: as (?:done|complete|completed))?(?: is (?:done|complete))?",
        body,
    ):
        slots = {"task": _task_hint(m.group(1))}
        if note:
            slots["note"] = note
        return Intent("task.complete", slots)
    if m := _m(r"(.+?) is (?:done|complete|completed|finished)", body):
        return Intent(
            "task.complete", {"task": _task_hint(m.group(1)), **({"note": note} if note else {})}
        )

    # Employee: blocker / resume / start
    if m := _m(r"(?:i(?:'m| am) (?:blocked|stuck)(?: on| with)?|(.+?) is blocked)(.*)", body):
        slots = {"task": _task_hint(m.group(1) or m.group(2))}
        if reason:
            slots["reason"] = reason
        return Intent("task.block", slots)
    if m := _m(
        r"(?:i(?:'m| am) (?:unblocked|back on)|(?:resume|resuming|continue|continuing)(?: work(?: on)?)?|the blocker is (?:fixed|resolved|gone))(.*)",
        body,
    ):
        return Intent("task.resume", {"task": _task_hint(m.group(1))})

    # Manager: approve / reject
    # "approved" too: the recogniser often hears "Approve it" as "Approved it".
    if m := _m(r"(?:approved?|accept the work on|accept(?:ed)?)\b(.*)", body):
        return Intent("task.approve", {"task": _task_hint(m.group(1))})
    if m := _m(r"(?:reject|send back|send it back|send that back|send this back)(.*)", body):
        slots = {"task": _task_hint(re.sub(r"^\s*(?:it|that|this)?\s*back\b", "", m.group(1)))}
        if reason:
            slots["reason"] = reason
        return Intent("task.reject", slots)

    # Manager: assign ready tasks / start project / manual assignment
    if m := _m(
        r"assign (?:all )?(?:the )?(?:ready|pending|open|remaining) tasks(?: by priority)?(?: (?:in|for|on) (?:the )?(.+?)(?: project)?)?(?: by priority)?",
        body,
    ):
        return Intent("project.assign_ready", {"project": m.group(1)} if m.group(1) else {})
    if m := _m(r"(?:start|launch|kick off|begin) (?:the )?(.+?) project", body):
        return Intent("project.start", {"project": m.group(1)})
    if m := _m(r"(?:assign|give) (?:the )?(.+?) to (.+)", body):
        return Intent("task.assign", {"task": _task_hint(m.group(1)), "person": m.group(2).strip()})

    # Employee: start work (after "start ... project")
    if m := _m(
        r"(?:i(?:'ve| have)? started|i(?:'m| am) starting|start|starting|begin|i'll start)(?: working on| work on)?(.*)",
        body,
    ):
        return Intent("task.start", {"task": _task_hint(m.group(1))})

    # Recognised but not supported by voice yet
    if re.search(r"\b(?:reassign|cancel (?:the )?task|delete (?:the )?task)\b", t):
        return Intent("change.not_yet", {"utterance": t})
    return None


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

    # --- things that change data (executed only through the harness, after "yes") ---
    if change := _change_intent(t, text):
        return change

    # --- read-only questions --------------------------------------------------------
    week = bool(re.search(r"\b(?:this week|weekly|the week)\b", t))
    period = {"period": "week" if week else "today"}
    if _m(
        r"(?:give me |read |what(?:'s| is) |tell me |read me )?(?:the |my )?(?:today's |daily |this week's |weekly |team )?"
        r"(?:summary|digest|report|status report|update|team update)(?: for (?:today|this week))?|"
        r"how is (?:my |the )?team doing(?: today| this week)?|team status",
        t,
    ):
        return Intent("query.summary", period)
    if _m(
        r"(?:who has |what is |what's |are there |any |show )?(?:the )?overdue(?: tasks| work)?|what(?:'s| is) overdue|who is late|what is late",
        t,
    ):
        return Intent("query.overdue")
    if _m(
        r"who(?:'s| is) (?:overloaded|free|busy|available)(?: right now| right| now)?|who has (?:capacity|room|time)|(?:team |the )?workload|who can take (?:more|another task)",
        t,
    ):
        return Intent("query.workload")
    if _m(
        r"how many tasks (?:were |have been |got )?(?:completed|finished|done)(?: today| this week)?",
        t,
    ):
        return Intent("query.completed", period)
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
    if _m(
        rf"(?:{_NAV} )?(?:my |the )?(?:settings|preferences|notification settings|voice settings)(?: page)?",
        t,
    ):
        return Intent("nav.settings")
    if _m(rf"(?:{_NAV} )?(?:the )?(?:voice |agent )?traces?(?: page)?", t):
        return Intent("nav.traces")
    if _m(rf"(?:{_NAV} )?(?:the )?system status(?: page)?", t):
        return Intent("nav.system")
    if _m(rf"(?:{_NAV} )?(?:all |my |the )*projects(?: page| list)?", t):
        return Intent("nav.projects")
    if _m(rf"(?:{_NAV} )?(?:the |my )?team(?: page)?", t):
        return Intent("nav.team")

    # "show the project team", "show tasks", "show the overview" (current project)
    if m := _m(
        rf"(?:{_NAV} )?(?:the )?(?:project )?(team|people|members|tasks|task|backlog|overview|summary)(?: tab| page| list)?",
        t,
    ):
        return Intent("nav.project_tab", {"tab": _TAB_WORDS[m.group(1)]})

    # "open the ecommerce project", "show the ecommerce team", "go to mobile banking tasks"
    if m := _m(
        rf"{_NAV} (?:the )?(.+?)(?: project)?(?:'s)?(?: (team|people|members|tasks|backlog|overview))?",
        t,
    ):
        query, tab = m.group(1).strip(), m.group(2)
        query = re.sub(r"^me ", "", query)  # "show me Arun"
        query = re.sub(r"(?:'s)? (?:page|profile|work|tasks?)$", "", query)  # "Arun's page"
        if query and query not in {"page", "screen", "it", "that", "this"}:
            slots = {"project": query}
            if tab:
                slots["tab"] = _TAB_WORDS[tab]
            return Intent("nav.project", slots)

    return Intent("unknown", {"utterance": t})
