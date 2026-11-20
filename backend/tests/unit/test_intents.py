import pytest

from app.agent.intents import parse


@pytest.mark.parametrize(
    ("said", "name", "slots"),
    [
        # navigation
        ("Open the E-Commerce project.", "nav.project", {"project": "ecommerce"}),
        (
            "Hey VoiceFlow, can you please open the e commerce project",
            "nav.project",
            {"project": "ecommerce"},
        ),
        ("go to mobile banking", "nav.project", {"project": "mobile banking"}),
        ("Show the E-Commerce team", "nav.project", {"project": "ecommerce", "tab": "team"}),
        ("take me to the hr portal tasks", "nav.project", {"project": "hr portal", "tab": "tasks"}),
        ("Show the project team.", "nav.project_tab", {"tab": "team"}),
        ("show tasks", "nav.project_tab", {"tab": "tasks"}),
        ("show the overview", "nav.project_tab", {"tab": "overview"}),
        ("Open my work", "nav.my_work", {}),
        ("go to my tasks", "nav.my_work", {}),
        ("open notifications", "nav.notifications", {}),
        ("show all projects", "nav.projects", {}),
        ("projects", "nav.projects", {}),
        ("open the team page", "nav.team", {}),
        ("system status", "nav.system", {}),
        ("Go back.", "nav.back", {}),
        ("go home", "nav.home", {}),
        # read-only questions
        ("What's my task?", "query.my_task", {}),
        ("what should I work on next", "query.my_task", {}),
        ("Read my notifications", "query.notifications", {}),
        ("any new notifications?", "query.notifications", {}),
        ("What is still pending?", "query.pending", {}),
        ("How is the e-commerce project going?", "query.pending", {"project": "ecommerce"}),
        ("read this page", "read_page", {}),
        ("where am I", "read_page", {}),
        # control
        ("stop", "cancel", {}),
        ("say that again", "repeat", {}),
        ("what can I say", "help", {}),
    ],
)
def test_parse(said, name, slots):
    intent = parse(said)
    assert intent.name == name, (said, intent)
    assert intent.slots == slots


@pytest.mark.parametrize(
    "said",
    [
        "I've completed the product listing page",
        "I have finished website testing",
        "approve it",
        "assign the ready tasks by priority",
        "A signed website testing to Subashini",  # STT error for "Assign" is still a change
        "I'm blocked because the API is down",
        "I need more time",
    ],
)
def test_changes_are_recognised_but_not_executed_yet(said):
    assert parse(said).name == "change.not_yet"


def test_nonsense_is_unknown_not_guessed():
    assert parse("purple elephants dancing").name == "unknown"
    assert parse("   ").name == "empty"
