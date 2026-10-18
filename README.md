# ReMind

**DubHacks 2026** · Community Kitchen track · Perceptron Robotics · SpaceXAI (Grok Voice) · MongoDB

ReMind is an AI companion that doesn't just talk: it helps people living with dementia take part in familiar activities through real-world interaction. A caregiver supervises each session. A conversational agent guides short, low-pressure activities, and an SO-101 robot arm moves everyday objects in response to the participant's choices.

> ReMind supports engagement. It is not a diagnostic or treatment tool and has not been clinically tested.

## Docs
- [Product & engineering spec](docs/SPEC.md)
- [Perceptron Robotics API notes](docs/PERCEPTRON_API.md)

## Team
- Maia Le ([@maiaPaperTowns](https://github.com/maiaPaperTowns))
- [@lkim0402](https://github.com/lkim0402)
- [@alesia-cameron](https://github.com/alesia-cameron)
- [@matthewcflam](https://github.com/matthewcflam)

## Repo layout

| Folder | What it is | Port |
| --- | --- | --- |
| [`frontend/`](frontend) | Next.js app: participant screen (`/participant`) and caregiver screen (`/caregiver`) | 3000 |
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

Open http://localhost:3000/caregiver, approve a session for the synthetic **Rose** profile, then open the participant screen.

Everything runs out of the box with a mock robot and in-memory storage. For the real setup, copy `.env.example` to `backend/.env` and `robot_worker/.env` and fill in:
- `MONGODB_URI` to persist data (the caregiver screen shows whether data is being saved)
- `XAI_API_KEY` + `XAI_MODEL` to use Grok for replies
- `ROBOT_MODE=perceptron` plus the Perceptron, SO-101 and camera settings, and run `uv sync --extra hardware` on the robot laptop

Backend tests: `cd backend && uv run pytest`

## How a turn flows

1. The participant taps **Tea**, or types/says it. `POST /api/agent/turn` returns a structured intent.
2. The backend checks the object and action against the activity allowlist, then moves the session to `validated`. The LLM never drives motors.
3. `POST /api/robot/jobs` checks that the robot is ready and not busy, and the worker checks its own allowlist again before moving.
4. The worker finishes moving and reports `verifying`. A caregiver confirms on `/caregiver` that the box is in the tray.
5. Only then does the agent say "We put the tea in the tray…" and save the preference (if the participant consented).

Stop (button, "stop" in chat, or the caregiver) halts the session and robot. Failures go to `needs_staff`, and a caregiver resumes the session. Set `REQUIRE_VERIFICATION=false` on the worker to skip step 4 when that's appropriate for a demo.

## Where to plug things in
- **Real robot:** start with [robot_worker/README.md](robot_worker/README.md) (connect, calibrate, teleop, record, scripted moves). Code lives in `robot_worker/worker/robot.py` (LeRobot SO-101 adapter) and `executors.py` (`PerceptronExecutor`). Check the action-chunk format against your deployment's contract.
- **Grok Voice:** the TODO in `frontend/app/participant/page.tsx` (mic input), with text replies from `backend/app/agent.py`.
- **Photon:** the TODO on the `help` intent in `backend/app/main.py`.
- **Activities / objects:** `backend/app/catalog.py` and `ALLOWED` in `robot_worker/worker/main.py`.
