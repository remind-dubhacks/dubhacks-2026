# ReMind

**DubHacks 2026** · Community Kitchen track · Perceptron Robotics · MongoDB

ReMind is an AI companion that doesn't just talk: it helps people living with dementia take part in familiar activities through real-world interaction. A caregiver supervises each session. A conversational agent guides short, low-pressure activities, and an SO-101 robot arm moves everyday objects in response to the participant's choices.

> ReMind supports engagement. It is not a diagnostic or treatment tool and has not been clinically tested.

## Docs
- [Product & engineering spec](docs/SPEC.md)
- [Perceptron Robotics API notes](docs/PERCEPTRON_API.md)
- [Training playbook: record, train and test the SO-101](docs/TRAINING.md)
- [Requirements and team roles](docs/REQUIREMENTS.md)
- [Code ownership (who edits which folder)](docs/OWNERSHIP.md)
- [Interface contracts](docs/CONTRACTS.md)

## Team
- Maia Le ([@maiaPaperTowns](https://github.com/maiaPaperTowns))
- [@lkim0402](https://github.com/lkim0402)
- Alesia Cameron [@alesia-cameron](https://github.com/alesia-cameron)
- [@matthewcflam](https://github.com/matthewcflam)

## Repo layout

| Folder | What it is | Port |
| --- | --- | --- |
| [`frontend/`](frontend) | Next.js app: patient screen (`/patient`), nurse screen (`/nurse`), robot tools (`/studio`), agent dev console (`/dev/voice`) | 3000 |
| [`backend/`](backend) | FastAPI session orchestrator: agent turns, allowlist validation, session state machine, MongoDB | 8000 |
| [`robot_worker/`](robot_worker) | Runs one allowlisted robot job at a time, either `mock` or `perceptron` (SO-101 + Perceptron policy) | 8001 |

## Getting started

You need Node 20+ and [uv](https://docs.astral.sh/uv/). Run each service in its own terminal.

```bash
cd robot_worker && uv sync && uv run uvicorn worker.main:app --port 8001
```

```bash
cd backend && uv sync && uv run uvicorn app.main:app --port 8000 --reload
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 (it redirects to `/patient`). Type the patient's first name, choose the games and press **Start**. After that the screen shows only the calm view, and the patient talks to ReMind by voice. Press **Esc** to bring the setup back or end the session. Session summaries appear on http://localhost:3000/nurse.

### Frontend layout
Routes in `frontend/app/` are thin. The code lives in feature folders:
- `features/patient/`: the patient screen. `CalmStage` renders the [Calm design system](design.md), `SetupCard` is the nurse's setup, and `useCompanion` handles the Gemini Live session, screen state and sounds.
- `features/nurse/`: the nurse screen.
- `app/studio/`: robot recording, training and vision tools (unchanged).
- `public/games/`: photos and sounds for the screen games. Credits are in each folder's `ATTRIBUTION.md`.

Everything runs out of the box with a mock robot and in-memory storage. For the real setup, copy `.env.example` to `backend/.env` and `robot_worker/.env` and fill in:
- `MONGODB_URI` (a free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster is enough) to persist residents, care-profile edits and the session summaries on the nurse screen. Without it everything resets on each backend restart, which `--reload` does on every file save. `/api/health` reports `"persistent": true` when Mongo is connected.
- `BACKBOARD_API_KEY`: **every voice call goes through [Backboard](https://docs.backboard.io) Realtime** (Gemini Live via Backboard), which also holds each patient's long-term memory. Realtime audio needs **paid Backboard credits**; the free starter credit is refused with `insufficient_credits`, and the patient screen shows that error. During development the direct-Gemini fallback is commented out (`# DEV: Backboard only` in `backend/app/voice/live.py` and `memory.py`), so there is no voice call without this key.
- How memory works: each resident who agreed to be remembered (`consentFlags.rememberPreferences`) has one Backboard assistant, named `ReMind memory: <participant id>`. It is created and seeded from the care profile at startup or on their first call. If our store loses the link, it is found again by name, so memories are never lost or split. During a call Backboard only reads memories (`memory="Readonly"`). After the call, what the person said is turned into new facts through Backboard's text API (`BACKBOARD_DIGEST_MODEL=provider/model`; empty means Backboard's default model) and saved. Memory only works when you pick a resident on the setup card: a name-only session, or `/dev/voice`, saves nothing. What it remembers: `GET /api/participants/{id}/memories`.
- `GEMINI_API_KEY` is still used by the text agent (`/api/agent/turn`, `/dev/voice` chat) and `scripts/eval_live.py`, not by voice calls. `ELEVENLABS_API_KEY` gives the text agent spoken replies.
- Pick a resident on the setup card and the companion uses their care profile (`careProfile` on the participant, edited with `PUT /api/participants/{id}/care-profile`): pacing for slow or stuttering speech, interests, topics to avoid. Use synthetic data only: the care profile and the conversation are sent to Backboard (and through it, to the model provider).
- `ROBOT_MODE=perceptron` plus the Perceptron, SO-101 and camera settings, and run `uv sync --extra hardware` on the robot laptop

Backend tests: `cd backend && uv run pytest`

## Games
The patient screen shows only what the agent's tools put on it: the gradient, one photo, or a few words. All games are spoken.

| Game | Based on | What the screen shows |
| --- | --- | --- |
| Famous faces (`faces`) | CST "Faces / scenes" | A photo, then the photo with the person's name |
| Sayings (`proverbs`) | CST "Word games" | A proverb with its last word missing, then the whole saying |
| Sounds (`sounds`) | CST "Sounds" | "Listen." while a clip plays, then what it was |
| Reorder (`reorder`) | Robot game | The target order (the robot shuffles the objects) |

The screen games follow the Cognitive Stimulation Therapy session themes from Woods et al., *Cognitive stimulation to improve cognitive functioning in people with dementia*, Cochrane Database of Systematic Reviews 2023 (CD005562.pub3). The agent asks for opinions rather than facts, never tests or corrects, and moves the conversation on by itself. If the patient stays silent, the relay nudges Gemini after 25 s. After three nudges in a row with no reply, it notes the patient as withdrawn and returns the screen to rest. Content lives in `backend/app/games/{faces,proverbs,sounds}.py`, and the tools are in `backend/app/voice/tools.py`.

## Robot job flow (API)

1. The participant taps **Tea**, or types/says it. `POST /api/agent/turn` returns a structured intent.
2. The backend checks the object and action against the activity allowlist, then moves the session to `validated`. The LLM never drives motors.
3. `POST /api/robot/jobs` checks that the robot is ready and not busy, and the worker checks its own allowlist again before moving.
4. The worker finishes moving and reports `verifying`. A caregiver confirms (`POST /api/robot/jobs/{id}/verify`) that the box is in the tray.
5. Only then does the agent say "We put the tea in the tray…" and save the preference (if the participant consented).

Stop (button, "stop" in chat, or the caregiver) halts the session and robot. Failures go to `needs_staff`, and a caregiver resumes the session. Set `REQUIRE_VERIFICATION=false` on the worker to skip step 4 when that's appropriate for a demo.

## Where to plug things in
- **Real robot:** start with [robot_worker/README.md](robot_worker/README.md) (connect, calibrate, teleop, record, scripted moves). Code lives in `robot_worker/worker/robot.py` (LeRobot SO-101 adapter) and `executors.py` (`PerceptronExecutor`). Check the action-chunk format against your deployment's contract.
- **Voice agent:** `backend/app/voice/` (`live.py` is the Gemini Live relay and `tools.py` holds the tools). Debug it at `/dev/voice`.
- **Photon:** the TODO on the `help` intent in `backend/app/main.py`.
- **Activities / objects:** `backend/app/catalog.py` and `ALLOWED` in `robot_worker/worker/main.py`.
