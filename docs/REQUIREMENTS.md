# ReMind: Requirements and Team Responsibilities

DubHacks 2026 | Reorder Game MVP | Complements [SPEC.md](SPEC.md) (this doc narrows scope to the shuffle-and-reorder game)

> ReMind supports engagement. It is not a diagnostic or treatment tool and has not been clinically tested. Do not claim it detects, measures or improves dementia.

## 1. Overview

A long-term care nurse staffs ~10 residents and cannot sit with each one. ReMind lets a caregiver launch short, automated cognitive games and check in on results from one screen. A conversational voice agent talks to the resident, picks a game from a **catalog**, and triggers the robot policy that runs it.

**MVP game: Reorder.** The SO-101 robot arm randomly shuffles a row of objects. The resident puts them back in the correct order. The camera checks the result, and the agent gives spoken feedback.

## 2. Users

| User | Needs |
| --- | --- |
| Resident (participant) | A low-pressure game by voice or touch. No score, no countdown, no shaming. |
| Caregiver / nurse | Start games for many residents, monitor live runs, review results, get alerted when something needs a human. |

## 3. Core user flow

1. Resident says something like "Let's play a game." The agent matches it to a game in the catalog (MVP: Reorder).
2. Backend validates the request (caregiver-approved session, game on allowlist, robot idle) and queues the robot job.
3. **Robot shuffles** the objects into a random order, then reports done.
4. Agent tells the resident the target order (for example "put the cup, the apple, then the book in a row, small to big, or by the reference card").
5. **Resident reorders** the objects by hand.
6. Resident says "done" (or taps Done). Camera captures the table; the vision step reads the object order.
7. **Correct:** agent says so and offers another round or a different game.
   **Wrong:** agent says it is not quite right and explains why in plain words (for example "the apple should come before the book"). Max **3 attempts** per round (configurable `MAX_TRIALS`). After the last attempt the agent shows the answer kindly (robot or screen) and moves on.
8. Results are saved, and the caregiver dashboard updates. A caregiver is messaged if needed.

## 4. Functional requirements

Priority: **P0** = must work in the demo, **P1** = should, **P2** = stretch.

### 4.1 Game: Reorder
| ID | Requirement | Pri |
| --- | --- | --- |
| G1 | Fixed set of 3 distinct, lightweight, easy-to-grasp objects (N configurable up to 4). Defined target order per round. | P0 |
| G2 | Robot shuffles objects into a random order that is **not** already the target order. | P0 |
| G3 | Resident reorders by hand; the system waits for a "done" signal (voice or button). | P0 |
| G4 | Vision reads the object order from the camera image and compares it with the target. | P0 |
| G5 | Up to `MAX_TRIALS` (default 3) attempts per round, with per-attempt feedback. | P0 |
| G6 | Wrong-answer feedback names which object(s) are misplaced and why, in one or two short sentences. | P0 |
| G7 | Difficulty levels: fewer objects, or a visual hint card. | P2 |

### 4.2 Conversational agent
| ID | Requirement | Pri |
| --- | --- | --- |
| A1 | Voice in/out (Grok Voice) plus typed/tap fallback. | P0 |
| A2 | Agent maps the resident's request to a game from the **catalog** and emits a **structured intent**. The LLM never drives motors. | P0 |
| A3 | Server checks consent, game allowlist and robot readiness before any robot job. | P0 |
| A4 | Tone rules: one short question at a time, never shame, never correct personal memories, no medical claims. | P0 |
| A5 | "Stop" by voice, button or caregiver halts the robot and session at once. | P0 |
| A6 | Catalog also lists future games (disabled, shown as "coming soon"). | P1 |

### 4.3 Robot and policy
| ID | Requirement | Pri |
| --- | --- | --- |
| R1 | Teleoperate with the leader arm to record demos of pick-and-place (shuffle moves). Record multiple successful runs. | P0 |
| R2 | Send the dataset to the Perceptron API to fine-tune a policy for the shuffle task. See [PERCEPTRON_API.md](PERCEPTRON_API.md). | P0 |
| R3 | Fallback: scripted executor with saved poses (`robot_worker/poses.json`) so the demo works if the policy is unreliable. | P0 |
| R4 | One job at a time, command allowlist, no autonomous retry after an error (errors go to `needs_staff`). | P0 |
| R5 | Fixed scene setup doc: lighting, camera height and angle, desk colour, object positions. The policy is very sensitive to these. | P0 |

### 4.4 Vision and evaluation
| ID | Requirement | Pri |
| --- | --- | --- |
| V1 | Capture an image on "done" and return the detected left-to-right order (Perceptron vision API or equivalent). | P0 |
| V2 | Return confidence. Low confidence means the agent asks the resident to adjust the objects, or asks for caregiver confirmation. | P0 |
| V3 | Produce a short reason string for a wrong order (feeds G6). | P0 |

### 4.5 Caregiver dashboard
| ID | Requirement | Pri |
| --- | --- | --- |
| C1 | Select a resident profile (pseudonymous) and approve/launch a game session. | P0 |
| C2 | Live view of session state, attempt number and robot status; Stop button. | P0 |
| C3 | Per-session result: correct or not, attempts used, time taken. Nonclinical wording only. | P0 |
| C4 | List of residents with last-run status (supports ~10 residents). | P1 |
| C5 | Alert to the caregiver (Photon message) on `needs_staff`, repeated failures, or a resident asking for help. | P1 |
| C6 | Trend view across sessions per resident. Show raw facts, not a "decline" score. | P2 |
| C7 | Delete a resident's data. | P1 |

### 4.6 Data
| ID | Requirement | Pri |
| --- | --- | --- |
| D1 | Store sessions, rounds, attempts, outcomes and timestamps in MongoDB (in-memory fallback). | P0 |
| D2 | Store resident preferences only with consent. | P1 |

## 5. Non-functional requirements

- **Safety:** clear robot workspace, physical e-stop reachable, supervised use only.
- **Robustness:** every spoken or on-screen step has a typed/tap fallback. Demo must survive Wi-Fi or API failure via mock/scripted modes.
- **Latency:** agent reply under about 2 s. Vision check under about 3 s.
- **Privacy:** pseudonymous profiles, no real PHI.
- **Accessibility:** large text, high contrast, one prompt at a time.

## 6. Architecture (reference)

```
Resident UI (Next.js)     Caregiver UI (Next.js)
          \                 /
           FastAPI orchestrator ---- MongoDB
            |        |      \
         Agent    Robot     Vision check
       (Grok)    worker     (camera + Perceptron)
                    |
                 SO-101 arm
                            Photon (caregiver alerts)
```

Repo layout: `frontend/`, `backend/`, `robot_worker/` (see [README](../README.md)).

### Session states for the Reorder game

```
idle -> consented -> game_selected -> shuffling -> awaiting_player
     -> checking -> (correct -> complete) | (wrong -> feedback -> awaiting_player, up to MAX_TRIALS)
     -> reveal -> complete
```
Any state can go to `stopped`. Hardware or vision errors go to `needs_staff`.

### Key interfaces (agree on these on day 1)

| Interface | Owner | Consumer | Shape |
| --- | --- | --- | --- |
| `GET /api/catalog` | Backend | Frontend, agent | `[{id, name, description, enabled}]` |
| Agent turn intent | Agent | Backend | `{intent: "start_game", game_id, ...}` |
| `POST /api/robot/jobs` | Backend | Robot worker | `{job: "shuffle", game_id, seed}` |
| `POST /api/vision/check` | Vision | Backend | request: image + target order. response: `{order: [...], correct: bool, confidence, reason}` |
| Session events | Backend | Both UIs | state, attempt, feedback text, result |

## 7. Team responsibilities

Each person owns one area end to end and is the reviewer for the interfaces they publish. Names are open; claim a role.

### Member 1: Robot and policy lead (hardware)
**Owns:** `robot_worker/`, teleop data, Perceptron fine-tune.
- Set up the SO-101 leader and follower, calibrate, and lock the scene (light, camera height, desk colour, object spots). Write a one-page scene checklist (R5).
- Record teleop demos of shuffle moves; collect many clean successful runs (R1).
- Upload the dataset, fine-tune via the Perceptron API, evaluate, and wire the policy into `perceptron.py` (R2).
- Maintain the scripted/pose-based fallback executor (R3) and the `shuffle` job with job allowlist and e-stop handling (R4).
- **Deliverable:** `shuffle` job that reliably randomizes the 3 objects, plus a recorded success video.

### Member 2: Vision and game logic
**Owns:** the "did the resident get it right" pipeline and game rules.
- Camera capture on "done"; detect the objects and their left-to-right order (V1).
- Compare with target, compute confidence, and produce the reason string for wrong answers (V2, V3).
- Implement game rules: target order, shuffle seed that is never already solved, attempt counter, `MAX_TRIALS`, reveal (G1, G2, G4, G5).
- Unit tests with saved photos of correct and incorrect arrangements, in different lighting.
- **Deliverable:** `POST /api/vision/check` and a game-rules module with tests.

### Member 3: Conversational agent and backend orchestration
**Owns:** `backend/`.
- Grok Voice integration, prompt and tone rules, structured intents (A1, A2, A4).
- Catalog (`catalog.py`, `GET /api/catalog`) with Reorder enabled and 2-3 "coming soon" entries (A6).
- Session state machine for the Reorder flow, allowlist/consent/readiness validation, stop handling (A3, A5).
- Wrong-answer feedback generation from the vision reason (G6).
- MongoDB storage of sessions, rounds and attempts (D1).
- **Deliverable:** end-to-end voice request to shuffle to check to feedback loop running against the mock robot, with `pytest` coverage.

### Member 4: Frontend, caregiver dashboard and alerts
**Owns:** `frontend/`, Figma wireframes, demo polish, Photon.
- Figma wireframes for resident screen, caregiver dashboard and game catalog, then implement them.
- Resident screen: big prompt, mic/tap controls, Done/Help/Stop, subtitles, robot status, no score (G3, A1).
- Caregiver dashboard: resident list, launch/approve, live monitor, results, Stop (C1-C4).
- Photon (or fallback) message to caregiver on `needs_staff` or help request (C5).
- Own the demo script, slides, and pitch.
- **Deliverable:** both screens working against the backend, plus the demo flow rehearsed.

### Cross-cutting
| Topic | Owner |
| --- | --- |
| Interface contracts in section 6 | Member 3 (publishes), all review |
| Integration testing on real hardware | Member 1 + Member 2 |
| Safety checklist and e-stop check before each run | Member 1 |
| Demo video and backup recording | Member 4 |

## 8. Milestones

| When | Goal |
| --- | --- |
| Hour 0-2 | Agree interfaces. Lock the scene and prop set. Wireframes drafted. Mock robot + mock vision wired end to end. |
| Hour 2-8 | Teleop demos recorded. Vision works on still photos. Agent runs the loop against mocks. Resident UI done. |
| Hour 8-16 | Fine-tuned policy tested (scripted fallback ready). Real camera feeds vision. Caregiver dashboard done. |
| Hour 16-22 | Full integration on hardware. Retries, edge cases, alerts. |
| Last 2 hours | Freeze features. Record a backup demo video. Rehearse. |

## 9. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Policy is sensitive to light, camera height, desk colour | Lock the scene early, tape marks on the desk, shade the setup, keep the checklist. |
| Fine-tuned policy fails or arrives late | Scripted pose executor (R3) is the default for the demo. |
| Vision misreads order | Confidence threshold, high-contrast distinct objects with labels, caregiver confirm button. |
| Voice recognition is noisy at the venue | Tap/type fallback for every step. |
| Scope creep (dementia detection, CV recommendations) | Out of scope for MVP (see below). |

## 10. Out of scope for the MVP

Diagnosing or scoring cognitive decline, deterioration detection, computer-vision-based recommendations, other robot games (only listed in the catalog as "coming soon"), arbitrary object grasping, and multi-robot support.

## 11. Definition of done (demo)

1. The caregiver approves a session for a resident profile.
2. The resident asks for a game by voice; the agent starts Reorder.
3. The robot shuffles 3 objects.
4. The resident reorders them and says "done".
5. The system correctly judges a correct and an incorrect arrangement, with spoken feedback and an explanation for the wrong one, within 3 attempts.
6. The result appears on the caregiver dashboard, and an alert reaches the caregiver when `needs_staff` is triggered.
