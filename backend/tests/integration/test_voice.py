"""Voice turns: navigation and read-only answers, grounded in permitted data only."""

import io
import os
import wave
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Task, TaskStatus
from app.voice.stt import FakeSpeechToText, FasterWhisperProvider, get_stt_provider
from tests.integration.test_projects_orchestrator import (
    make_project,
    skilled_world,  # noqa: F401  (fixture)
    started_project,
)

pytestmark = pytest.mark.integration


def wav(seconds=1.0, rate=16_000, channels=1, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate) * channels)
    return buf.getvalue()


def say(api, text, path=None, summary=None):
    resp = api.post(
        "/voice/turns", json={"text": text, "path": path, "page_summary": summary}, key=None
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def speak_audio(api, fake, data=None, path=None):
    api.client.app.dependency_overrides[get_stt_provider] = lambda: fake
    return api.client.post(
        "/api/v1/voice/turns/audio" + (f"?path={path}" if path else ""),
        content=data if data is not None else wav(),
        headers={"X-CSRF-Token": api.csrf, "Content-Type": "audio/wav"},
    )


# ----------------------------------------------------------------------------- navigation


def test_open_project_by_spoken_name(as_user, skilled_world):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    for said in ("Open the E-Commerce project", "hey voiceflow, go to e commerce please"):
        r = say(mgr, said)
        assert r["outcome"] == "ok"
        assert r["action"] == {"type": "navigate", "to": f"/projects/{project['id']}"}
        assert r["speech"].startswith("Opening E-Commerce. 0 of 6 tasks are done.")


def test_project_team_uses_the_current_screen(as_user, skilled_world):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    here = f"/projects/{project['id']}"
    r = say(mgr, "show the project team", path=here)
    assert r["action"]["to"] == f"{here}?tab=team"
    r = say(mgr, "show the E-Commerce tasks")
    assert r["action"]["to"] == f"{here}?tab=tasks"
    r = say(mgr, "show the team")  # no project on screen: the Team page
    assert r["action"]["to"] == "/team"


def test_unknown_and_ambiguous_projects_ask_instead_of_guessing(as_user, skilled_world):  # noqa: F811
    mgr = as_user("manager_web")
    make_project(mgr, skilled_world, name="Mobile App")
    make_project(mgr, skilled_world, name="Mobile Banking")
    r = say(mgr, "open the mobile project")
    assert r["outcome"] == "clarify" and r["action"] is None
    assert "Mobile App" in r["speech"] and "Mobile Banking" in r["speech"]

    r = say(mgr, "open the spaceship project")
    assert r["outcome"] == "clarify"
    assert r["speech"].startswith("I couldn't find a project called spaceship.")


def test_other_organisations_projects_are_invisible(as_user, skilled_world):  # noqa: F811
    started_project(as_user, skilled_world)
    r = say(as_user("manager_b"), "open the e-commerce project")
    assert r["outcome"] == "clarify" and r["action"] is None


def test_employees_cannot_open_manager_pages(as_user, skilled_world):  # noqa: F811
    _, project, _ = started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    assert say(emp, "open the team page")["outcome"] == "denied"
    r = say(emp, "show the project team", path=f"/projects/{project['id']}")
    assert r["outcome"] == "denied" and r["action"] is None
    assert say(emp, "open my work")["action"] == {"type": "navigate", "to": "/my-work"}


# ----------------------------------------------------------------------------- answers


def test_whats_my_task_is_read_from_the_database(as_user, skilled_world):  # noqa: F811
    started_project(as_user, skilled_world)
    r = say(as_user("emp_web_1"), "What's my task?")
    assert r["speech"].startswith("Your current task is Database schema. It is new, high priority")
    r = say(as_user("emp_web_2"), "what should i work on")
    assert "UI mockups" in r["speech"]


def test_what_is_pending_gives_a_project_grounded_breakdown(as_user, skilled_world):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    r = say(mgr, "What is still pending?", path=f"/projects/{project['id']}")
    assert r["speech"].startswith("E-Commerce: 0 of 6 tasks are done.")
    assert "2 in progress" in r["speech"] and "3 waiting on other tasks" in r["speech"]
    assert "1 needs your decision: iOS build setup." in r["speech"]


def test_read_notifications_counts_unread(as_user, skilled_world):  # noqa: F811
    started_project(as_user, skilled_world)
    r = say(as_user("emp_web_1"), "read my notifications")
    assert r["speech"] == "You have 1 new notification. New task: Database schema."
    assert r["action"] == {"type": "navigate", "to": "/notifications"}


def test_read_this_page_speaks_the_screen_summary(as_user, skilled_world):  # noqa: F811
    r = say(as_user("manager_web"), "read this page", summary="Projects. 1 active project.")
    assert r["speech"] == "Projects. 1 active project."


def test_change_commands_do_not_change_anything_yet(as_user, skilled_world, db):  # noqa: F811
    _, project, _ = started_project(as_user, skilled_world)
    r = say(as_user("emp_web_1"), "I've completed the database schema")
    assert r["outcome"] == "not_yet" and r["action"] is None
    t1 = db.execute(select(Task).where(Task.external_key == "T1")).scalar_one()
    assert t1.status is TaskStatus.ASSIGNED


def test_voice_turns_need_csrf(as_user, skilled_world):  # noqa: F811
    mgr = as_user("manager_web")
    resp = mgr.client.post("/api/v1/voice/turns", json={"text": "open projects"})
    assert resp.status_code == 403


# ----------------------------------------------------------------------------- audio


def test_audio_turn_uses_speech_recognition_with_name_hints(as_user, skilled_world):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    fake = FakeSpeechToText("Open the E-Commerce project.")
    resp = speak_audio(mgr, fake)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transcript"] == "Open the E-Commerce project."
    assert body["action"]["to"] == f"/projects/{project['id']}"
    assert "Emp Web 1" in fake.calls[0] and "E-Commerce" in fake.calls[0]


def test_unclear_audio_asks_to_repeat_and_does_nothing(as_user, skilled_world):  # noqa: F811
    resp = speak_audio(as_user("manager_web"), FakeSpeechToText("open proj", confident=False))
    body = resp.json()
    assert body["heard_clearly"] is False
    assert body["outcome"] == "repeat" and body["action"] is None


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"not audio at all", 422, "audio_invalid"),
        (wav(rate=44_100), 422, "audio_invalid"),
        (wav(channels=2), 422, "audio_invalid"),
        (wav(seconds=0.05), 422, "audio_too_short"),
        (wav(seconds=25), 413, "audio_too_large"),
    ],
)
def test_bad_audio_is_rejected_before_recognition(as_user, skilled_world, data, status, code):  # noqa: F811
    fake = FakeSpeechToText("open projects")
    resp = speak_audio(as_user("manager_web"), fake, data=data)
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code
    assert fake.calls == []


# ----------------------------------------------------------------------------- real model (opt-in)

SAMPLE = Path(r"D:\voiceflow-spike\audio\test1.wav")


@pytest.mark.skipif(
    not os.environ.get("VOICEFLOW_RUN_STT_TESTS") or not SAMPLE.exists(),
    reason="set VOICEFLOW_RUN_STT_TESTS=1 (needs the base.en model and the sample recording)",
)
def test_real_whisper_transcribes_the_sample_with_name_hints():
    provider = FasterWhisperProvider("base.en", 4)
    t = provider.transcribe(SAMPLE.read_bytes(), hints=["Subashini", "Priya", "Arun"])
    assert t.confident
    assert "Subashini" in t.text
    assert "high" in t.text.lower() and "tomorrow" in t.text.lower()
