# CLAUDE.md --- Voice-First Agentic Task Management System

> **Purpose:** This is the master product, architecture, engineering,
> and implementation guide for Claude Code. Read this file before
> proposing or changing the project. Treat it as the source of truth
> unless the project owner explicitly approves a change.

------------------------------------------------------------------------

## 1. Product vision

Build a company task-management application in which managers and
employees interact with the system primarily through voice. A manager
can speak a task-allocation instruction; the system understands the
request, validates it, selects the correct employee, creates the
assignment, and informs the employee through speech. Employees can ask
what they need to do, report progress, request help or more time, and
report completion by voice. After a task is genuinely completed, the
system can select the next eligible task from the shared task pool
according to deterministic business rules.

This is not simply a chatbot or a CRUD task application. It is a
**voice-first task-management product with an agent interface, a
controlled execution harness, and a deterministic task orchestrator**.

### Primary product outcomes

1.  Eliminate repetitive one-by-one task assignment after a project backlog is configured.
2.  Let managers start a prepared project once and let the system coordinate its task execution automatically.
3.  Make employee task updates easy through hands-free voice interaction.
4.  Improve task visibility, dependency-aware prioritisation, workload balance, and accountability.
5.  Prevent the AI from inventing tasks, employees, deadlines,
    permissions, or completion facts.
6.  Make every important agent action traceable, auditable, testable, and recoverable.

### Product name

Use the working name **VoiceFlow --- Agentic Task Management**. Keep
branding configurable; do not hard-code the name throughout the
codebase.

------------------------------------------------------------------------

## 2. Non-negotiable product principles

-   Voice is the primary and intended interaction mode for managers and
    employees.
-   Do not make typing or touch interaction necessary for ordinary task
    workflows after initial setup.
-   Use spoken responses, spoken confirmations, and spoken
    notifications.
-   The UI must still provide accessible visual status,
    captions/transcripts, and recovery controls. These are supporting
    accessibility and safety features, not the primary workflow.
-   Never silently execute a high-impact or ambiguous action based on
    uncertain speech recognition.
-   The LLM interprets natural language; trusted application code
    validates permissions and performs state changes.
-   The LLM must never invent employees, tasks, task IDs, priorities,
    deadlines, skill profiles, or task-completion evidence.
-   The task orchestrator, not the LLM, evaluates the project dependency graph and decides which pending tasks are eligible for assignment.
-   A project backlog is prepared and stored before project execution. The manager should not need to allocate each task individually.
-   Multiple independent tasks may be assigned in parallel to different qualified employees, subject to workload limits and project policy.
-   A dependent task must remain blocked until all required predecessor tasks satisfy their configured completion/approval conditions.
-   If no task is eligible, or an exception requires human judgement, notify the manager with a clear reason and wait for an authorized decision; do not invent work or force an assignment.
-   Do not automatically assign a task to an employee merely because it
    has the highest priority. Check skills, availability, workload,
    dependencies, deadlines, and assignment policy.
-   All state-changing actions must be validated, authorized, idempotent
    where possible, and logged.
-   Build a modular monolith first. Do not introduce microservices
    without a demonstrated need.
-   Prefer open-source/local-first components where practical. Do not
    introduce paid APIs or services without asking the project owner.
-   Do not add LangChain or LangGraph by default. Build a small,
    explicit agent loop and orchestration layer so the control flow
    remains understandable and testable.
-   Do not claim that an external notification, speech, or AI action
    succeeded until the relevant service confirms success.

------------------------------------------------------------------------

## 3. User roles and permissions

### 3.1 Manager

A manager can, subject to their team scope:

-   Create a project by voice and identify an existing prepared backlog.
-   Import, review, or approve a complete project task backlog before execution.
-   Start, pause, resume, or close a project by voice.
-   Set project-level policies for priority, dependencies, staffing, approvals, and workload limits.
-   Handle exceptions, blocked tasks, unresolved dependencies, and tasks with no suitable employee.
-   Manually override an assignment only when needed; this is an exception path, not the normal workflow.
-   Set or change priority and deadline.
-   Ask for task, team, workload, and delay summaries.
-   Approve tasks that require manager approval.
-   Reassign, cancel, or reprioritise tasks.
-   Receive completion, delay, and blocker notifications.
-   Review audit history and agent traces through an authorized
    administrative interface.

### 3.2 Employee

An employee can:

-   Ask what their current task is.
-   Ask for their pending, completed, or next tasks.
-   Hear task details, priority, deadline, and acceptance criteria.
-   Accept or decline an assignment when company policy permits.
-   Report progress.
-   Report a blocker and request help.
-   Request a deadline extension.
-   Say that a task is complete.
-   Provide completion evidence using supported mechanisms.
-   Hear their next eligible task when auto-assignment is enabled.

Employees must never access another employee's private task details
unless their role and team permissions explicitly allow it.

### 3.3 Administrator

An administrator manages:

-   Organizations, teams, users, roles, and permissions.
-   Employee skills and availability.
-   Task categories and assignment policies.
-   Voice settings and notification preferences.
-   Retention, audit, and security settings.

### 3.4 Authorization rules

-   Enforce authorization on the backend for every API and tool call.
-   Never rely on hidden UI controls as a security boundary.
-   Scope every task query to the authenticated user's organization and
    permitted team.
-   A manager cannot assign work outside their authorized team.
-   An employee cannot complete, cancel, or reassign another employee's
    task.
-   Record the actor, action, target, timestamp, and outcome for every
    important state transition.
-   Use secure authentication and short-lived access tokens with
    refresh-token rotation or a secure session strategy.
-   Do not store raw passwords, access tokens, or secrets in logs.

------------------------------------------------------------------------

## 4. Core user journeys

### 4.1 Project setup and one-time backlog preparation

The normal workflow is project-first, not one-task-at-a-time assignment. A project backlog containing (for example) 60 tasks is prepared before execution. It may be created through an approved import/template or entered by an authorized project planner. The backlog must include, as available:
- task title and description;
- priority and due date or milestone;
- dependencies (predecessor task IDs);
- required skills/role;
- estimated effort;
- acceptance criteria and completion evidence;
- whether manager approval is required.

Validate the complete backlog before allowing the manager to start the project. Detect missing dependencies, cycles, unknown predecessor IDs, duplicate task identifiers, impossible dependency chains, missing required fields, and invalid priority values. Show or speak a summary and require manager approval to activate the project. Do not let the LLM invent missing backlog tasks or dependencies.

### 4.2 Manager starts the project by voice

Example:

> "Start the E-Commerce Application Development project."

Expected flow:
1. Authenticate the manager and resolve the project within their authorized organization/team scope.
2. Confirm that the project backlog has passed validation and is approved for execution.
3. Summarize the project, total task count, currently ready tasks, blocked-by-dependency tasks, and any staffing gaps.
4. Ask for spoken confirmation to start the project.
5. Change project status to `ACTIVE` in a transaction and record an audit event.
6. Trigger the deterministic orchestrator to evaluate the dependency graph and allocate all currently eligible tasks in parallel, subject to capacity and policy.
7. Notify assigned employees by voice and send the manager a concise project-start summary.

The manager must not have to assign each of the 60 tasks individually. Manual assignment is available only as an override or exception workflow.

### 4.3 Dependency-aware automatic allocation

For every active project, the orchestrator repeatedly evaluates the task graph:
1. Find tasks whose status is `PENDING` and whose required predecessor tasks are all completed (or approved, where policy requires approval).
2. Exclude cancelled, blocked, already assigned, reserved, or otherwise ineligible tasks.
3. Match each ready task to employees using required skills, role, availability, workload capacity, team membership, and assignment fairness.
4. Rank ready tasks by eligibility first, then dependency readiness, priority, deadline urgency, milestone impact, and age; use workload balance and fairness when choosing among qualified employees.
5. Allocate as many independent ready tasks as policy and employee capacity allow. Use transactions, row-level locking or equivalent concurrency control, and idempotency to prevent duplicate assignments.
6. Notify each employee of their assignment and notify the manager with a summary, not a separate approval request for every ordinary task.
7. Re-run evaluation whenever a task is completed/approved, an employee becomes available, a blocker is resolved, or a manager changes project policy.

A dependency graph must be acyclic. Use topological readiness checks; do not assign a downstream task before its dependencies are satisfied. High priority does not override an unmet dependency.

### 4.4 Manual assignment override (exception path)

Normal work is assigned by the orchestrator (4.2, 4.3). A manager may still
assign a single task directly when an exception requires it. Example spoken
instruction:

> "Assign website testing to Subashini. It is high priority and should
> be completed by tomorrow."

Expected flow:

1.  Activate the manager's voice session using a wake word or explicit
    voice-session control.
2.  Capture speech and produce a transcript.
3.  Detect intent: `create_and_assign_task`.
4.  Extract structured fields:
    -   task title: Website testing
    -   assignee: Subashini
    -   priority: high
    -   due date: tomorrow, resolved in the organization's timezone
    -   description and acceptance criteria, if supplied
5.  Resolve the employee against the authenticated manager's permitted
    team.
6.  Check that required fields are present and valid.
7.  Read back a concise confirmation: "I heard: assign Website testing
    to Subashini, high priority, due tomorrow. Should I assign it?"
8.  Require an unambiguous spoken confirmation before committing the
    assignment.
9.  The harness validates authorization and input.
10. The task service writes the task and assignment in a database
    transaction.
11. The system confirms the committed result and notifies the employee.
12. Record a trace and audit event.

If the employee name matches multiple people, ask a disambiguating
question. Never guess.

### 4.5 Manager adds tasks to the shared task pool

Example:

> "Add API testing as a high-priority task to the unassigned task pool.
> It must be completed by Friday."

The task is created with `UNASSIGNED` status. The system must not invent
an employee assignment.

### 4.6 Employee asks for their task

Example:

> "What is my current task?"

Flow:

1.  Authenticate the employee's voice session.
2.  Retrieve tasks only for that employee.
3.  Read the current task and relevant details aloud.
4.  If there is no current task, explain that clearly and optionally
    report the next pending task.

### 4.7 Employee reports completion

Example:

> "I have completed website testing."

Flow:

1.  Resolve the employee from the authenticated session, not from a name
    guessed by the LLM.
2.  Identify the task from the employee's active assignments.
3.  If more than one task could match, ask which task they mean.
4.  Read back the task title.
5.  Ask for confirmation before changing status.
6.  Check the task's completion criteria and required evidence.
7.  If evidence or manager approval is required, move the task to
    `PENDING_REVIEW`.
8.  Otherwise mark it `COMPLETED`.
9.  Record who reported completion, when, and what evidence or checks
    were used.
10. Notify the manager.
11. Trigger the orchestrator to evaluate the next task only after the
    completion transaction succeeds.

A spoken "done" is a completion claim, not proof that work is complete.

### 4.8 Automatic next-task and project-wide allocation

After a task is completed or approved, the orchestrator re-evaluates the entire active project, not merely a personal queue:

1.  Mark the completed predecessor and update its status history.
2.  Recalculate which downstream tasks have now become dependency-ready.
3.  Evaluate all currently ready tasks against employee skills, availability, workload, and team policy.
4.  Apply deterministic ranking rules and allocate eligible work across the team, allowing independent tasks to run in parallel.
5.  Prefer a suitable employee who has capacity; do not assume the employee who completed the previous task must receive the next one.
6.  If no task is eligible, do not fabricate or force an assignment. Tell affected employees that no task is ready and notify the manager with the reason (for example, all remaining tasks depend on unfinished work, no qualified employee is available, or a blocker needs intervention).
7.  If a task specifically requires manager approval, place it in the approval queue and notify the manager. Ordinary tasks should not require per-task manager approval unless configured.
8.  Assign using a transaction and concurrency protection so two workers cannot claim the same task.
9.  Notify employees by voice and send the manager batched/proactive project updates according to notification preferences.

Priority ranking must be configurable and deterministic. A recommended
initial ordering is: - eligibility and dependency checks first; -
required skills and employee suitability; - priority; - deadline
urgency; - age of task / creation time; - workload balancing and
fairness as tie-breakers.

Do not use an LLM to choose the next task.


### 4.9 Project-level status and manager escalation

The manager should receive proactive summaries rather than having to ask for every update. Summaries should include total tasks, completed tasks, in-progress tasks, pending tasks, dependency-blocked tasks, tasks awaiting review, overdue tasks, active blockers, and tasks with no suitable employee. Provide a spoken daily/periodic digest and event-based alerts for urgent exceptions.

When the manager asks "What is still pending?", answer with a project-grounded breakdown. Distinguish clearly between:
- **Ready to assign:** dependencies satisfied, but no assignment yet;
- **In progress:** currently owned by an employee;
- **Blocked by dependency:** predecessor work is unfinished;
- **Blocked by issue:** an employee reported a blocker;
- **Awaiting review:** completion has been submitted but approval/evidence is pending;
- **Needs manager decision:** no qualified employee, conflicting priorities, scope change, overdue critical task, or an approval is required.

Do not treat all pending tasks as assignable. The manager should be notified when the project cannot progress automatically, with the reason and the specific decision needed.

### 4.10 Blocker and extension flow

Example:

> "I am blocked because the API is unavailable."

The agent should: - identify the active task; - ask a short follow-up if
the blocker is unclear; - create a blocker record linked to the task; -
notify the manager; - avoid marking the task complete; - pause or adjust
assignment eligibility according to policy.

For an extension request, capture the requested date, reason, and task.
Do not change the deadline until an authorized manager approves it,
unless the organization explicitly configures another policy.

### 4.11 Manager asks for team status

Examples: - "How many tasks were completed today?" - "Who has overdue
tasks?" - "Which high-priority tasks are still pending?" - "Who is
overloaded?" - "What is blocking the API project?"

The agent must answer from authorized database queries and state the
reporting period/timezone. If data is unavailable, say so instead of
fabricating an answer.

------------------------------------------------------------------------

## 5. Voice-only interaction and accessibility

### 5.0 Voice-only navigation (owner requirement, 2026-11-20)

Every screen and action must be reachable by voice alone. The user should
not need to read or type during ordinary work.

-   Navigation commands open screens directly: "open my tasks", "go to
    project board", "show team workload", "open notifications", "go
    back", "go home".
-   "Read this page" / "what's on screen?" speaks a short summary of the
    current screen (e.g. "Project board. 12 in progress, 3 blocked, 2
    awaiting your review.").
-   Navigation changes no data, so it runs immediately without a
    confirmation question. It is still an allowlisted intent; unknown
    destinations get a spoken "I can open: ..." list.
-   Every screen defines its spoken summary alongside its visual layout.
-   The UI stays professional and easy to understand visually, but text
    is a supporting layer (captions, recovery controls), never required.
-   The browser requires one initial click to grant microphone and audio
    permission; say so honestly during first-run setup.

### 5.1 Voice interaction model

Support: - Push-to-talk as a reliable fallback. - Optional wake-word
activation for hands-free use. - Spoken responses through
text-to-speech. - Voice notifications for new assignments, reminders,
and status changes. - Interruption and cancellation commands such as
"stop", "cancel", and "repeat". - Short spoken confirmations for
high-impact actions. - Session timeout and explicit mute controls.

The application must not continuously record or upload ambient
conversations. Wake-word detection should run locally where possible;
only send audio for processing after activation and user consent.

### 5.2 Browser and operating-system limitations

A web application cannot guarantee zero-touch operation in every browser
and operating system. Microphone permissions, notification permissions,
autoplay/audio policies, login, device selection, and recovery may
require initial user interaction. Design a guided first-run setup and
explain these limitations honestly.

### 5.3 Speech pipeline

Use provider interfaces so speech engines can be swapped:

-   `SpeechToTextProvider`
-   `TextToSpeechProvider`
-   `WakeWordProvider` (optional)
-   `AudioInputProvider`
-   `AudioOutputProvider`

Prefer an open-source STT/TTS implementation that can run locally or on
infrastructure controlled by the organization. Evaluate accuracy,
latency, language support, hardware requirements, licensing, and Windows
compatibility before selecting a provider.

Potential candidates to evaluate, not automatically assume: - STT:
Whisper implementations, whisper.cpp, sherpa-onnx. - TTS: Piper and
other maintained open-source engines. - Wake word: open-source local
wake-word engines.

Do not hard-code a specific vendor into business logic. Add a provider
adapter and configuration.

### 5.4 Speech recognition safeguards

-   Preserve the transcript and confidence metadata according to privacy
    policy.
-   If confidence is low, ask the speaker to repeat.
-   Names, dates, numbers, priorities, and task titles require careful
    confirmation.
-   Normalize dates using the organization's configured timezone.
-   Do not infer a missing deadline or priority.
-   Do not treat background speech as an instruction.
-   Do not execute commands from audio that is not associated with an
    authenticated user session.
-   Support the organization's required languages; begin with English
    and make language support extensible. Add Tamil support only after
    testing real speech samples and pronunciation quality.

### 5.5 Text is still used internally

The product is voice-first for users, but internally it must store
structured records, transcripts where permitted, task descriptions, API
payloads, logs, and traces. Provide captions/transcripts as an
accessibility and troubleshooting option. Do not confuse a voice-only
user experience with a text-free backend.

------------------------------------------------------------------------

## 6. Recommended technology architecture

Use a TypeScript-first web stack with a Python backend. Confirm the
repository's existing setup before installing or replacing dependencies.

### Frontend

-   Vite
-   React
-   TypeScript
-   React Router
-   Tailwind CSS
-   A consistent component system such as shadcn/ui, where useful
-   Web Audio APIs for audio capture/playback
-   Browser Speech APIs only as optional fallback, not the sole
    production speech solution
-   TanStack Query for server state if needed
-   Zustand or React Context for small client-side session state

### Backend

-   Python 3.11+
-   FastAPI
-   Pydantic for request/response validation
-   SQLAlchemy 2.x
-   Alembic for migrations
-   PostgreSQL
-   Redis only when required for queues, distributed locks, or ephemeral
    session state
-   WebSockets or Server-Sent Events for live events, selected based on
    the actual requirements
-   Background worker for reminders and notification delivery

### Agent and orchestration

-   A small custom agent loop.
-   Explicit intent schemas and tool contracts.
-   Deterministic task orchestrator.
-   Execution harness for validation, authorization, confirmation,
    retries, idempotency, and logging.
-   LLM provider adapter so local/open models can be evaluated and
    changed.
-   Do not add LangChain/LangGraph unless a documented need is
    demonstrated and the project owner approves it.

### Quality and operations

-   Pytest for backend tests.
-   Vitest and React Testing Library for frontend tests.
-   Playwright for browser end-to-end tests.
-   Structured JSON logging.
-   OpenTelemetry-compatible tracing where useful.
-   Evaluation datasets and repeatable agent evaluations.
-   Docker Compose for local development and reproducible services.

Keep the frontend and backend in one repository initially.

------------------------------------------------------------------------

## 7. High-level architecture

``` text
                 MANAGER / EMPLOYEE
                         |
                 Voice-first UI (Vite)
                         |
             Audio capture / playback layer
                         |
             STT adapter       TTS adapter
                   \             /
                    \           /
                 Voice session manager
                         |
                 Agent interface layer
                         |
              Intent extraction / dialogue
                         |
              Structured validated command
                         |
             EXECUTION HARNESS / GUARDRAILS
              |          |          |
          AuthZ       Validation  Confirmation
              |          |          |
              +----------+----------+
                         |
                TASK ORCHESTRATOR
              /          |          \
       Task service  Assignment   Notification
                     policy          service
              \          |          /
                    PostgreSQL
                         |
                Audit events / traces
                         |
               Evaluation and monitoring
```

### Component responsibilities

**Frontend voice layer** - Starts and stops voice sessions. - Captures
audio after activation. - Plays speech output. - Shows optional visual
status, captions, and accessible recovery controls. - Does not decide
permissions or task allocation.

**Voice session manager** - Associates audio input with an authenticated
user. - Manages session state, turn-taking, interruption, timeout, and
language. - Passes recognized utterances to the agent layer.

**Agent interface** - Understands intent and extracts structured
arguments. - Asks clarifying questions. - Uses only registered tools. -
Does not access the database directly.

**Execution harness** - Validates schemas and business constraints. -
Checks authenticated identity and permissions. - Requires confirmation
for sensitive state changes. - Executes tools safely. - Handles
idempotency, timeouts, retries, and errors. - Emits traces and audit
events.

**Task orchestrator** - Owns task lifecycle transitions and assignment
decisions. - Applies deterministic priority and eligibility policy. -
Prevents duplicate assignment. - Runs only after successful state
transitions.

**Task service** - Creates, reads, updates, and transitions task
records. - Enforces task lifecycle rules.

**Notification service** - Sends in-app events and voice
notifications. - Tracks delivery state and retries. - Does not mark a
task complete merely because a notification was delivered.

------------------------------------------------------------------------

## 8. Agent loop and harness design

### 8.1 Agent loop

Use an explicit bounded loop:

1.  Receive an utterance from an authenticated voice session.
2.  Obtain STT transcript and confidence.
3.  Detect intent.
4.  Extract arguments into a strict Pydantic schema.
5.  If required information is missing or ambiguous, ask a spoken
    clarification.
6.  Propose a tool call from an allowlisted tool registry.
7.  Pass the proposed action to the execution harness.
8.  Harness validates identity, permission, schema, business rules, and
    confirmation.
9.  Execute the approved tool.
10. Return the real tool result to the agent.
11. Generate a concise spoken response grounded in that result.
12. Record the trace and finish the turn.

Set a maximum number of model/tool iterations per turn. Prevent infinite
loops. Never let the model call arbitrary URLs, SQL, shell commands, or
unregistered functions.

### 8.2 Harness responsibilities

The harness is the trusted control layer between the LLM and application
services.

Required checks: - authenticated principal exists; - role and
organization scope are valid; - requested employee/task is resolvable; -
caller has permission; - arguments pass strict schema validation; - task
state transition is legal; - confirmation exists where required; -
request has an idempotency key for retry-sensitive mutations; -
concurrency and duplicate assignment protections are active; - tool
result is recorded; - failure is handled without pretending success.

### 8.3 Tool registry

Start with a small allowlist:

-   `find_employee`
-   `get_my_tasks`
-   `get_task_details`
-   `create_task`
-   `add_task_to_pool`
-   `assign_task`
-   `request_task_completion`
-   `approve_task_completion`
-   `report_task_progress`
-   `report_task_blocker`
-   `request_deadline_extension`
-   `get_team_task_summary`
-   `get_overdue_tasks`
-   `get_next_eligible_task`
-   `send_notification`

Each tool must have: - typed input schema; - typed output schema; -
authorization policy; - side-effect classification; - confirmation
requirement; - timeout and retry policy; - audit event name; - unit and
evaluation tests.

Do not expose database sessions or unrestricted repository methods as
LLM tools.

------------------------------------------------------------------------

## 9. Task lifecycle and business rules

Recommended initial task statuses:

``` text
DRAFT
  -> UNASSIGNED
  -> ASSIGNED
  -> ACCEPTED
  -> IN_PROGRESS
  -> PENDING_REVIEW
  -> COMPLETED

Other transitions:
ASSIGNED / ACCEPTED / IN_PROGRESS -> BLOCKED
BLOCKED -> IN_PROGRESS
UNASSIGNED / ASSIGNED -> CANCELLED
ASSIGNED / ACCEPTED -> UNASSIGNED (declined or unassigned; record history)
PENDING_REVIEW -> IN_PROGRESS (rejected with reason)
PENDING_REVIEW -> COMPLETED (approved)
```

Define and test a transition table in backend code. Reject invalid
transitions.

Clarifications (2026-11-20):

-   **"Waiting on dependencies" is computed, not stored.** A task is
    *ready* when it is `UNASSIGNED` and all predecessors are
    `COMPLETED`. Wherever this document says `PENDING` for orchestrator
    readiness, it means `UNASSIGNED`.
-   **`BLOCKED` means only "an employee reported a blocker".** Waiting on
    predecessor tasks is the separate, computed "blocked by dependency"
    category used in reports.
-   **Reassignment is a history event, not a status.** A reassigned task
    is `ASSIGNED` to the new employee, with the change recorded in
    `task_assignments` and `task_status_history`.

See `docs/decisions.md` for owner-approved product decisions (auto-accept,
WIP limits, evidence policies, etc.) and the Phase 0 measurements.

### Task fields

At minimum: - id (UUID) - organization_id - team_id - project_id - title -
description - acceptance_criteria - priority (`LOW`, `MEDIUM`, `HIGH`,
`URGENT`) - status - created_by - assigned_to (nullable) - created_at -
updated_at - due_at (nullable) - timezone - estimated_effort
(optional) - required_skills (optional structured relation) - depends_on
(optional task relations) - requires_approval -
completion_evidence_policy - version (for optimistic concurrency)

### Employee fields

At minimum: - id - organization_id - team_id - display_name - role -
active status - skills (structured relation) - availability status -
workload capacity - voice/language preferences - notification
preferences

Do not store sensitive employee information unless necessary and
approved.

### Assignment policy

Implement a deterministic, configurable scoring/ranking policy. A
candidate task is eligible only if: - it is pending and unassigned; -
its dependencies are satisfied; - the employee is active and
available; - the employee has required skills or a configured exception
applies; - workload limits are not exceeded; - the task belongs to the
employee's permitted organization/team; - the task is not reserved or
claimed by another process.

Use a database transaction and row-level locking or an equivalent
concurrency-safe strategy when claiming a task. Add tests for two
workers attempting to claim the same task.

------------------------------------------------------------------------

## 10. API design

Use versioned REST endpoints under `/api/v1`. Use WebSockets or SSE for
live events only where needed. All endpoints require authentication
except explicitly public health/readiness endpoints.

### Authentication and users

``` text
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/users/me
GET    /api/v1/teams/{team_id}/employees
GET    /api/v1/employees/{employee_id}
PATCH  /api/v1/employees/{employee_id}
```

### Projects and backlog

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/backlog/import
POST   /api/v1/projects/{project_id}/backlog/validate
GET    /api/v1/projects/{project_id}/dependency-graph
POST   /api/v1/projects/{project_id}/approve-backlog
POST   /api/v1/projects/{project_id}/start
POST   /api/v1/projects/{project_id}/pause
POST   /api/v1/projects/{project_id}/resume
POST   /api/v1/projects/{project_id}/close
GET    /api/v1/projects/{project_id}/progress
GET    /api/v1/projects/{project_id}/pending-and-blocked
```

Backlog import should support a validated structured format (for example CSV/JSON or a project template) so dozens or hundreds of tasks can be loaded in one operation. The manager may initiate and approve the project by voice; bulk backlog authoring/import may be performed during project setup by an authorized planner.

### Tasks

``` text
POST   /api/v1/tasks
GET    /api/v1/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
POST   /api/v1/tasks/{task_id}/assign
POST   /api/v1/tasks/{task_id}/accept
POST   /api/v1/tasks/{task_id}/start
POST   /api/v1/tasks/{task_id}/progress
POST   /api/v1/tasks/{task_id}/block
POST   /api/v1/tasks/{task_id}/request-completion
POST   /api/v1/tasks/{task_id}/approve-completion
POST   /api/v1/tasks/{task_id}/reject-completion
POST   /api/v1/tasks/{task_id}/cancel
POST   /api/v1/tasks/{task_id}/reassign
GET    /api/v1/me/tasks
GET    /api/v1/me/tasks/current
GET    /api/v1/me/tasks/next
```

### Task pool and assignment

``` text
POST   /api/v1/task-pool
GET    /api/v1/task-pool
POST   /api/v1/task-pool/{task_id}/claim
POST   /api/v1/assignment-policy/evaluate
```

The evaluation endpoint should be internal/authorized and must not
itself assign a task unless explicitly designed to do so.

### Voice and agent sessions

``` text
POST   /api/v1/voice/sessions
POST   /api/v1/voice/sessions/{session_id}/turns
POST   /api/v1/voice/sessions/{session_id}/end
GET    /api/v1/voice/settings
PATCH  /api/v1/voice/settings
```

For streaming audio, design a WebSocket endpoint after selecting and
documenting the STT transport. Do not send large raw audio blobs through
ordinary JSON requests without a reason.

### Notifications and reporting

``` text
GET    /api/v1/notifications
POST   /api/v1/notifications/{notification_id}/acknowledge
GET    /api/v1/reports/team-summary
GET    /api/v1/reports/overdue
GET    /api/v1/reports/workload
GET    /api/v1/audit-events
```

### API requirements

-   Use Pydantic request/response models.
-   Return consistent error structures.
-   Use pagination and filtering for collection endpoints.
-   Validate organization/team scope.
-   Add idempotency keys to retry-sensitive mutations.
-   Document APIs with FastAPI OpenAPI.
-   Never expose secrets or internal stack traces to clients.
-   Do not create every endpoint at once; implement them as vertical
    slices.

------------------------------------------------------------------------

## 11. Suggested database model

Create normalized PostgreSQL tables, adapting names and relationships as
implementation requires:

-   `organizations`
-   `teams`
-   `users`
-   `roles` / role assignments
-   `employee_skills`
-   `tasks`
-   `task_dependencies`
-   `task_assignments`
-   `task_status_history`
-   `task_completion_evidence`
-   `task_blockers`
-   `deadline_extension_requests`
-   `notifications`
-   `voice_sessions`
-   `agent_traces`
-   `agent_trace_steps`
-   `audit_events`
-   `idempotency_records`
-   `assignment_policy_settings`

Use UUID primary keys, foreign keys, indexes, timestamps, and
appropriate uniqueness constraints. Use database migrations; never rely
on manually editing production tables.

Keep task status history and assignment history rather than overwriting
the only record of prior state.

------------------------------------------------------------------------

## 12. UI/UX requirements

The interface should look polished, modern, calm, and professional. It
should feel like a voice assistant for a real workplace, not a generic
admin template.

### Main screens

1.  First-run setup and microphone permission guidance.
2.  Login/authentication.
3.  Manager voice workspace.
4.  Employee voice workspace.
5.  Live task overview.
6.  Task pool and priority queue.
7.  Team workload and progress overview.
8.  Task details and completion review.
9.  Notifications and activity history.
10. Settings for voice, language, accessibility, and privacy.

### Visual direction

-   Responsive desktop and mobile layouts.
-   Clear typography and consistent spacing.
-   Professional neutral palette with one restrained accent color.
-   Strong visual hierarchy and clear status indicators.
-   Subtle, purposeful animation.
-   Voice activity indicator with listening, processing, speaking,
    muted, and error states.
-   Live waveform or audio-level visualization where appropriate.
-   Clear distinction between manager and employee workspaces.
-   Accessible contrast, keyboard support, screen-reader labels, and
    reduced-motion support.
-   Avoid clutter, excessive gradients, excessive glass effects, and
    decorative charts that do not communicate useful information.

### Voice-first UX states

Show clear states such as: - Ready to listen - Listening -
Understanding - Need clarification - Waiting for confirmation -
Executing action - Completed successfully - Failed / retry available -
Muted / microphone unavailable

A visual indicator must never imply that the microphone is active when
it is not. Always provide a visible mute/stop option even in a
voice-first product.

------------------------------------------------------------------------

## 13. Notifications and reminders

Support: - New task assigned. - Task due soon. - Task overdue. - Task
blocked. - Completion awaiting review. - Task completion
approved/rejected. - Next task assigned. - Manager summary.

Use a background scheduler/worker for reminders. Avoid sending duplicate
reminders. Store delivery attempts and outcomes. Respect quiet hours and
user preferences. Voice playback should occur only when the user has
enabled it and the device/session permits it.

------------------------------------------------------------------------

## 14. Traces, auditability, and observability

Every agent turn should produce a trace with a correlation ID.

Suggested trace fields: - trace_id - session_id - organization_id -
actor_user_id - actor_role - timestamp - transcript reference or
redacted transcript - STT provider and confidence - detected intent -
extracted structured arguments - validation results - proposed tool -
authorization result - confirmation state - tool execution result - task
IDs affected - response generation metadata - latency measurements -
error category

Never log passwords, tokens, raw credentials, or unnecessary sensitive
audio. Apply retention and redaction policies.

Keep **agent traces** separate from **audit events**: - Traces explain
how a request was processed. - Audit events record authoritative
business actions and who performed them.

------------------------------------------------------------------------

## 15. Evaluation and testing strategy

Treat evaluation as a core engineering layer, not a final activity.

### 15.1 Intent and extraction evaluations

Build a dataset of realistic manager and employee utterances,
including: - clear task assignment; - missing employee; - duplicate
employee names; - ambiguous task title; - missing priority; - relative
dates such as tomorrow and Friday; - noisy speech and low STT
confidence; - unsupported request; - Tamil/English mixed-language
samples if multilingual support is introduced.

Measure: - intent classification accuracy; - field-level extraction
accuracy; - employee resolution accuracy; - date and priority extraction
accuracy; - clarification correctness; - unsafe-action rate.

### 15.2 Tool and workflow evaluations

Test: - correct tool selection; - unauthorized assignment rejection; -
employee isolation; - confirmation before mutations; - duplicate
assignment prevention; - task lifecycle correctness; - next-task
selection correctness; - notification delivery and retry; - recovery
after database or model failure.

### 15.3 Metrics

Track: - task assignment success rate; - task completion transition
accuracy; - unauthorized action rate (target zero); - duplicate
assignment rate (target zero); - false completion rate (target zero); -
intent accuracy; - structured extraction accuracy; - clarification
rate; - STT word error rate on a representative dataset; - end-to-end
response latency; - notification delivery success; - trace completeness.

### 15.4 Test layers

-   Unit tests for policy, validation, schemas, and state transitions.
-   Integration tests for database, services, and APIs.
-   Contract tests for speech and LLM provider adapters.
-   Agent evaluations using fixed datasets.
-   End-to-end tests for manager and employee workflows.
-   Security tests for role boundaries and organization isolation.
-   Concurrency tests for task claiming and assignment.
-   Manual usability tests with real speakers, accents, devices, and
    workplace noise.

Use deterministic fake providers in automated tests. Do not make the
test suite depend on paid or unreliable external APIs.

------------------------------------------------------------------------

## 16. Security, privacy, and reliability

-   Use TLS in deployed environments.
-   Store secrets in environment variables or a secret manager, never in
    source control.
-   Provide `.env.example` with placeholders only.
-   Enforce backend authentication and authorization on every protected
    route.
-   Validate all model-generated tool arguments as untrusted input.
-   Protect against prompt injection in task descriptions and other
    user-controlled content.
-   Treat task descriptions, transcripts, and retrieved records as data,
    never as instructions to override system policy.
-   Apply rate limits to authentication, voice sessions, and expensive
    model calls.
-   Restrict audio retention; obtain consent and document processing.
-   Encrypt sensitive data at rest where appropriate.
-   Add backups and a tested restore process.
-   Use transactions for multi-record state changes.
-   Use idempotency and concurrency controls for assignments.
-   Provide graceful fallback when STT, TTS, LLM, or notification
    services are unavailable.
-   Never mark a task complete or assigned if the database transaction
    failed.
-   Do not expose internal prompts, secrets, traces, or other users'
    data to employees.

------------------------------------------------------------------------

## 17. Repository structure

Start with a clean monorepo. Adapt if a repository already exists;
inspect before changing it.

``` text
voiceflow/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── app/
│       ├── components/
│       │   ├── voice/
│       │   ├── layout/
│       │   └── ui/
│       ├── features/
│       │   ├── auth/
│       │   ├── manager/
│       │   ├── employee/
│       │   ├── tasks/
│       │   ├── task-pool/
│       │   ├── notifications/
│       │   └── reports/
│       ├── hooks/
│       ├── services/
│       ├── state/
│       ├── types/
│       └── tests/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   │   ├── tasks/
│   │   │   ├── assignment/
│   │   │   ├── notifications/
│   │   │   └── voice/
│   │   ├── agent/
│   │   │   ├── loop.py
│   │   │   ├── intents/
│   │   │   ├── tools/
│   │   │   ├── harness/
│   │   │   ├── orchestrator/
│   │   │   ├── policies/
│   │   │   └── providers/
│   │   ├── observability/
│   │   └── workers/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── evaluations/
│       └── security/
├── docs/
│   ├── architecture.md
│   ├── api-contracts.md
│   ├── task-lifecycle.md
│   ├── voice-design.md
│   ├── security.md
│   └── evaluation-plan.md
└── scripts/
```

Do not create all files as empty placeholders. Create modules when their
responsibility is being implemented.

------------------------------------------------------------------------

## 18. Implementation roadmap

Build in small, working vertical slices. At the end of each phase, run
tests and explain what works.

### Phase 0 --- Discovery and design

-   Inspect the repository and existing dependencies.
-   Confirm the current runtime, operating system, and deployment
    target.
-   Create a concise implementation plan.
-   Decide the first STT/TTS providers through a small compatibility
    spike.
-   Confirm authentication strategy and organization/team model.
-   Document unresolved decisions; do not silently assume them.

Deliverables: architecture diagram, key decisions, initial repository
plan, provider spike plan.

### Phase 1 --- Project foundation

-   Create Vite + React + TypeScript frontend.
-   Create FastAPI backend.
-   Configure PostgreSQL and migrations.
-   Add environment configuration and health endpoints.
-   Add linting, formatting, and test commands.
-   Add Docker Compose for local development.

Acceptance: frontend and backend start locally; database migration and
health checks work.

### Phase 2 --- Authentication and roles

-   Implement manager, employee, and administrator roles.
-   Implement organization and team scoping.
-   Protect APIs and add authorization tests.

Acceptance: employees cannot access other employees' private data;
managers are restricted to their permitted teams.

### Phase 3 --- Task core

-   Implement task CRUD, task pool, assignment, status history, and
    lifecycle transitions.
-   Add deterministic assignment policy.
-   Add concurrency and idempotency safeguards.

Acceptance: tasks can be created, assigned, progressed, and completed
through tested APIs.

### Phase 4 --- Voice foundation

-   Implement audio capture and playback UI.
-   Integrate STT/TTS through provider interfaces.
-   Add session state, confidence handling, interruption, and spoken
    clarification.
-   Add a guided microphone setup.

Acceptance: a user can speak a test phrase and hear a response; provider
failure is handled safely.

### Phase 5 --- Agent and harness

-   Implement intent schemas and a small allowlisted tool registry.
-   Implement the bounded agent loop.
-   Implement validation, authorization, confirmation, idempotency, and
    traces.
-   Use deterministic mock LLM/STT/TTS providers in tests.

Acceptance: the agent can interpret a supported request but cannot
bypass the harness.

### Phase 6 --- Project backlog and manager voice activation

-   Create project records and support bulk backlog import/template loading.
-   Validate task metadata and dependency graph, including cycle detection.
-   Let the manager review/approve the backlog and start, pause, or resume a project by voice.
-   Trigger project-wide scheduling after the manager confirms project activation.

Acceptance: a manager can start a prepared multi-task project by voice without assigning tasks one by one.

### Phase 7 --- Employee voice workflow

-   Support current task, task details, progress, blocker, extension
    request, and completion request.
-   Add completion evidence and optional manager review.

Acceptance: an employee can manage their assigned work by voice with
correct permission boundaries.

### Phase 8 --- Automatic next-task orchestration

-   Trigger only after successful completion/approval.
-   Evaluate eligible tasks deterministically.
-   Assign atomically and prevent duplicate claims.
-   Speak the next task to the employee.

Acceptance: the next eligible task is assigned once, to a suitable
employee, according to policy.

### Phase 9 --- Manager insights and notifications

-   Add team summaries, overdue tasks, workload, and completion reports.
-   Add reminder scheduling and delivery tracking.
-   Support spoken summaries.

Acceptance: manager queries return database-grounded answers and
notifications are auditable.

### Phase 10 --- Evaluation, hardening, and deployment

-   Expand evaluation datasets.
-   Test noisy speech and realistic workflows.
-   Perform security and concurrency testing.
-   Add monitoring, backups, retention, and deployment documentation.

Acceptance: release checklist passes and known limitations are
documented.

------------------------------------------------------------------------

## 19. Development rules for Claude Code

Before changing code:

1.  Read this file fully.
2.  Inspect the repository, existing files, dependencies, and current
    branch.
3.  Do not overwrite existing work without understanding it.
4.  Identify the smallest useful implementation slice.
5.  Explain the proposed change and files affected before a large
    implementation.
6.  Ask before adding paid services, external accounts, or new
    infrastructure.
7.  Ask before changing major architecture or replacing dependencies.
8.  Do not invent product requirements when a decision is unresolved;
    list the options and recommend one.
9.  Keep secrets out of code and logs.
10. Do not claim tests passed unless they were actually run.

While coding:

-   Follow separation of concerns.
-   Use typed interfaces and schemas.
-   Keep business rules out of React components and LLM prompts.
-   Keep database access out of the LLM.
-   Keep task assignment logic deterministic and independently testable.
-   Use migrations for schema changes.
-   Add tests with each meaningful feature.
-   Handle loading, empty, permission-denied, and error states in the
    UI.
-   Keep components accessible and responsive.
-   Do not use mock data in production paths.
-   Label demo data clearly.
-   Do not create unnecessary abstractions or premature microservices.
-   Do not implement the entire roadmap in one uncontrolled
    code-generation step.

After each implementation slice, report: - What was implemented. - Files
created or changed. - API routes added or changed. - Database changes
and migration names. - Tests executed and their actual results. - How to
run and manually verify the feature. - Known limitations and the next
smallest step.

------------------------------------------------------------------------

## 20. Definition of done

A feature is complete only when: - its intended user journey works; -
authentication and authorization are enforced server-side; - input and
state transitions are validated; - errors and recovery are handled; -
important actions are auditable; - traces are available where the agent
is involved; - automated tests pass; - UI is responsive and
accessible; - documentation is updated; - no unsupported success claim
or fabricated data is present.

The whole product is not complete merely because the UI looks finished
or the LLM can produce a convincing spoken answer.

------------------------------------------------------------------------

# 21. Ready-to-paste master prompt for Claude Code

Copy the prompt below into Claude Code after placing this file at the
project root as `CLAUDE.md`.

------------------------------------------------------------------------

You are acting as a senior product architect, staff-level full-stack
engineer, AI agent engineer, and UX engineer.

I want to build **VoiceFlow --- Agentic Task Management**, a voice-first
task allocation and employee tracking application.

First, read the complete `CLAUDE.md` file. It contains the product
requirements, architecture, agent/harness boundaries, API plan, data
model, security rules, evaluation strategy, UI/UX direction, and phased
roadmap. Treat it as the project source of truth.

## Your first task: plan, do not code yet

I do not want you to immediately generate the whole application. Start
in Plan mode and do the following:

1.  Inspect the existing repository and identify what already exists.
2.  Explain the product in your own words to confirm your understanding.
3.  Produce the end-to-end manager and employee voice workflows.
4.  Produce a clear architecture diagram showing frontend, audio
    pipeline, STT, TTS, voice session manager, agent loop, execution
    harness, tool registry, task orchestrator, backend services,
    PostgreSQL, notifications, traces, and evaluations.
5.  Explain the difference between the LLM, agent loop, harness, tools,
    and deterministic orchestrator, using this project as the example.
6.  Propose the exact frontend and backend technology choices, with
    reasons.
7.  Compare suitable open-source STT, TTS, and optional wake-word
    choices. Consider Windows compatibility, deployment, language
    support, latency, accuracy, hardware, and licensing. Do not assume a
    provider works without verification.
8.  Propose authentication and authorization for managers, employees,
    administrators, organizations, and teams.
9.  Design the task lifecycle, task-pool model, priority policy,
    employee matching, completion verification, and automatic next-task
    allocation.
10. Define the API contracts and database schema needed for the first
    working release.
11. Define the trace format, audit-event model, agent evaluation
    datasets, metrics, and test plan.
12. Divide implementation into small phases with clear acceptance
    criteria.
13. Identify unresolved product decisions and ask me only the most
    important questions before implementation.

## Critical rules

-   Do not start coding during this first planning task.
-   Do not create or modify files until I approve the plan.
-   Do not assume that "voice-only" removes the need for backend text,
    structured data, logs, or accessible recovery controls.
-   Design for hands-free operation after initial setup, while
    respecting browser and operating-system permission restrictions.
-   Do not make continuous ambient recording the default.
-   Do not let the LLM invent tasks, employees, deadlines, priorities,
    permissions, or completion evidence.
-   Do not let the LLM directly modify the database.
-   All state-changing actions must pass through the execution harness.
-   The task orchestrator must make next-task decisions
    deterministically.
-   Require spoken confirmation for ambiguous or consequential actions.
-   Verify task completion according to task-specific criteria; a spoken
    claim alone is not proof.
-   Prevent duplicate task assignments using transactions, concurrency
    controls, and idempotency.
-   Enforce authorization in the backend, not only in the frontend.
-   Do not add LangChain or LangGraph by default. Explain any proposed
    framework before adding it.
-   Prefer open-source and locally controllable services. Do not
    introduce paid APIs without my approval.
-   Do not generate the complete project in one shot.
-   Use clean, production-minded code, tests, migrations, documentation,
    and accessible UI.
-   Never say a command, test, API, or integration works unless it has
    actually been verified.

## Expected output from this planning task

Return these sections in order:

1.  Understanding of the product
2.  Manager workflow
3.  Employee workflow
4.  End-to-end architecture diagram
5.  Agent loop vs harness vs orchestrator explanation
6.  Recommended technology stack
7.  STT/TTS/wake-word comparison
8.  Authentication and authorization design
9.  Database entities and relationships
10. API design
11. Task lifecycle and automatic assignment algorithm
12. Trace and evaluation architecture
13. UI/UX screen plan
14. Security and privacy risks
15. Phased implementation plan
16. Open questions and recommended decisions

Be specific to this application. Avoid generic AI-agent explanations.
Explain trade-offs in simple, clear language. Wait for my approval
before writing code.

------------------------------------------------------------------------

## 22. Final instruction

Build a reliable task-management product with a voice-first experience,
not a voice demo. Correctness, authorization, task-state integrity,
safety, and traceability are more important than making the agent appear
autonomous. Autonomy must operate inside explicit policies and a
controlled execution harness.
