# Plan: nurse view to manage each patient's context

Status: steps 1–4 are built. `/nurse` has urgent alerts, a resident carousel, Sessions / Memories / Context tabs, the
consent toggle and "forget everything" (`backend/tests/test_nurse.py`). Not built yet: the review queue (3) and the
nurse PIN. This followed persistent Backboard memory (`backend/app/voice/memory.py`).

## Goal
A nurse can open any resident and see or change everything the companion knows about them:
- the **care profile**: pacing, interests, topics to avoid, calming strategies
- the **long-term memories** in their Backboard assistant
- **consent**
- **past sessions**

Today the nurse screen (`frontend/features/nurse/NurseScreen.tsx`) only lists session summaries.

## What exists to build on
| Need | Already there |
| --- | --- |
| Residents | `GET/POST /api/participants`, `GET/DELETE /api/participants/{id}` |
| Care profile | `PUT /api/participants/{id}/care-profile` (`CareProfile` in `backend/app/models.py`); new lines are added to memory |
| Memories (read) | `GET /api/participants/{id}/memories` → `memory.list_all` |
| One assistant per resident | `memory.ensure_assistant`, named `ReMind memory: <participant id>` |
| Session summaries | `companion_sessions` collection, `GET /api/voice/sessions` |
| Storage | MongoDB Atlas (`MONGODB_URI`); required for edits to survive restarts |

Backboard endpoints we will use (from the backboard-sdk client):
- `POST /assistants/{id}/memories` `{content, metadata}`
- `PUT /assistants/{id}/memories/{memory_id}` `{content, metadata}`
- `DELETE /assistants/{id}/memories/{memory_id}`
- `GET /assistants/{id}/memories/stats`
- `DELETE /assistants/{id}`

## 1. Backend (`backend/app/main.py`, `backend/app/voice/memory.py`)
- `memory.update(aid, mid, content)` and `memory.delete(aid, mid)`, best effort like the other calls.
- `memory.list_all` also returns `metadata.kind` and `created_at`, so the UI can show where a fact came from:
  `care_profile` (seeded), `session` (learnt in a call) or `nurse` (added by hand).
- Routes (each one 404s for an unknown resident, and creates the assistant with `ensure_assistant` if it is
  missing):
  - `POST /api/participants/{id}/memories` `{content}` → saved with `kind="nurse"`
  - `PATCH /api/participants/{id}/memories/{mid}` `{content}`
  - `DELETE /api/participants/{id}/memories/{mid}`
  - `GET /api/participants/{id}/sessions` → that resident's `companion_sessions`, newest first
  - `PUT /api/participants/{id}/consent` `{rememberPreferences}`:
    - turning it off stops saving at once (the after-call digest already checks the flag)
    - with `?forget=true` it also deletes the Backboard assistant, so nothing remembered is kept
- Tests in `backend/tests/test_memory.py`, with the existing `backboard` MockTransport fixture.

## 2. Frontend (`frontend/features/nurse/`, `frontend/lib/api.ts`)
- **Resident list**: name, last session, memory count, consent badge, plus "Add resident".
- **Resident detail**, with tabs:
  - **Care profile**: a form over `CareProfile`. List fields (interests, avoid topics, life story) are editable
    lists; saving calls `PUT /care-profile`.
  - **Memories**: list with a source filter (care profile / learnt / nurse) and a search box. Edit in place,
    delete with a confirm, add a fact. Learnt facts show the date they were learnt.
  - **Sessions**: the existing summaries (games played, observations, alerts), for this resident only.
  - **Consent**: the remember toggle, plus a "forget everything" button with a confirm.
- Use the Calm design system styles (`frontend/app/globals.css`, `Patient Design System/`), with large type and
  plain words.

## 3. Optional: review queue for learnt facts
Facts from a call are saved as `kind="session_pending"` and appear in a "To review" list. The nurse approves
(becomes `session`) or deletes each one.

**Check before building:** during a call, Backboard Readonly recall must ignore pending facts. If Backboard can't
filter memories by metadata, keep pending facts in Mongo instead and write each one to Backboard only when
approved.

## 4. Access and data
- Put a nurse PIN or shared secret (an env var checked by a FastAPI dependency) on every `/api/participants/*`
  write route before any deployment beyond a laptop demo.
- Synthetic data only until there is real auth and a data agreement: care profiles and conversations go to
  Backboard and the model provider.

## Order of work
1. Memory edit/delete/add routes, plus tests.
2. Resident detail with the Memories tab (most useful for testing memory by hand).
3. Care-profile form and Sessions tab.
4. Consent and forget.
5. Review queue (optional) and the nurse PIN.

## Done when
- A nurse can add "Rose's favourite food is hot dogs" by hand, start a call as Rose, and ask about it.
- They can delete it, and the next call no longer knows it.
- All of this still holds after a backend restart, with Mongo connected.
