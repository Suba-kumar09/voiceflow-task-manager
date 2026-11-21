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
    ("said", "name", "slots"),
    [
        # employee
        (
            "I've completed the product listing page",
            "task.complete",
            {"task": "product listing page"},
        ),
        ("I have finished website testing.", "task.complete", {"task": "website testing"}),
        ("I'm done", "task.complete", {"task": ""}),
        (
            "I've completed the product listing page, note: All products show price, stock and images.",
            "task.complete",
            {"task": "product listing page", "note": "All products show price, stock and images"},
        ),
        ("Mark the wishlist page as done", "task.complete", {"task": "wishlist page"}),
        ("The catalog API is done", "task.complete", {"task": "catalog api"}),
        (
            "I'm blocked because the Payment Sandbox is down.",
            "task.block",
            {"task": "", "reason": "the Payment Sandbox is down"},
        ),
        ("I'm stuck on the cart API", "task.block", {"task": "cart api"}),
        ("I'm unblocked", "task.resume", {"task": ""}),
        ("I've started the database schema", "task.start", {"task": "database schema"}),
        ("start my task", "task.start", {"task": ""}),
        # manager
        ("Approve it", "task.approve", {"task": ""}),
        ("approve the UI design mockups", "task.approve", {"task": "ui design mockups"}),
        (
            "Send it back because the tests are failing",
            "task.reject",
            {"task": "", "reason": "the tests are failing"},
        ),
        ("Assign the ready tasks by priority", "project.assign_ready", {}),
        ("a signed the ready tasks", "project.assign_ready", {}),  # misheard "assign"
        (
            "assign the ready tasks in the e-commerce project",
            "project.assign_ready",
            {"project": "ecommerce"},
        ),
        ("Start the HR portal project", "project.start", {"project": "hr portal"}),
        (
            "A signed website testing to Subashini",
            "task.assign",
            {"task": "website testing", "person": "subashini"},
        ),
        (
            "give the wishlist page to Priya",
            "task.assign",
            {"task": "wishlist page", "person": "priya"},
        ),
        # confirmation
        ("Yes", "confirm.yes", {}),
        ("yes please, go ahead", "confirm.yes", {}),
        ("Okay, do it.", "confirm.yes", {}),
        ("no, not now", "confirm.no", {}),
        ("go ahead", "confirm.yes", {}),
        ("No", "confirm.no", {}),
        # Phase 8: extensions, decline, progress
        ("I need more time", "task.extend", {"task": "", "when": "i need more time"}),
        (
            "I need more time on the cart API until Friday because the sandbox is down",
            "task.extend",
            {
                "task": "cart api",
                "when": "i need more time on the cart api until friday",
                "reason": "the sandbox is down",
            },
        ),
        (
            "Can I get two more days?",
            "task.extend",
            {"task": "", "when": "can i get two more days"},
        ),
        (
            "I need more time on the cart API for three more days",
            "task.extend",
            {"task": "cart api", "when": "i need more time on the cart api for three more days"},
        ),
        (
            "I need an extension for the wishlist page",
            "task.extend",
            {"task": "wishlist page", "when": "i need an extension for the wishlist page"},
        ),
        ("Approve the extension", "extension.approve", {"task": ""}),
        ("Approved the extension.", "extension.approve", {"task": ""}),  # real mishearing
        ("Approved it.", "task.approve", {"task": ""}),
        ("approve the extension for the cart API", "extension.approve", {"task": "cart api"}),
        (
            "Deny the extension because the launch date is fixed",
            "extension.deny",
            {"task": "", "reason": "the launch date is fixed"},
        ),
        (
            "I can't do the wishlist page because I have no React access",
            "task.decline",
            {"task": "wishlist page", "reason": "I have no React access"},
        ),
        ("decline it", "task.decline", {"task": ""}),
        (
            "I'm about 60 percent done with the catalog API",
            "task.progress",
            {"task": "catalog api", "percent": "60"},
        ),
        ("I'm halfway through", "task.progress", {"task": "", "percent": "50"}),
        (
            "progress on the cart API is 30 percent",
            "task.progress",
            {"task": "cart api", "percent": "30"},
        ),
        # still unsupported by voice
        ("reassign the cart API", "change.not_yet", {"utterance": "reassign the cart api"}),
    ],
)
def test_change_commands_and_slots(said, name, slots):
    intent = parse(said)
    assert (intent.name, intent.slots) == (name, slots), said


def test_nonsense_is_unknown_not_guessed():
    assert parse("purple elephants dancing").name == "unknown"
    assert parse("   ").name == "empty"
