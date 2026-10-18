# Interface contracts

Change these only by PR with all four members reviewing. JSON is camelCase.

## Backend HTTP API (Member 3 publishes, Member 4 consumes)

Existing endpoints are in `backend/app/main.py` (sessions, participants, `agent/turn`, `robot/jobs`, `robot/stop`). To add for the Reorder game:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/catalog` | `[{id, name, description, enabled}]`; Reorder enabled, others "coming soon" |
| `POST /api/sessions/{sid}/done` | Resident says "done"; triggers the vision check, returns `{correct, attemptsLeft, feedback, revealed}` |

## Vision (Member 2 publishes, Member 3 consumes)

`POST /api/vision/check` (implemented, mock by default)

```json
// request
{"target": ["cup", "apple", "book"], "imageB64": null, "mockOrder": null}
// response
{"order": ["apple","cup","book"], "correct": false, "confidence": 0.93,
 "needsConfirm": false, "misplaced": ["cup","apple"],
 "reason": "The cup should be in spot 1, where the apple is now."}
```

Python rules: `app.games.reorder.shuffled(target, seed)`, `evaluate(target, observed)`, `MAX_TRIALS = 3`.

## Robot worker (Member 1 publishes, Member 3 consumes)

Worker runs on port 8001: `GET /health`, `POST /jobs`, `GET /jobs/{id}`, `POST /stop`. To add: a `shuffle` action

```json
{"jobId": "...", "actionId": "shuffle", "objectId": "reorder_set", "seed": 42}
```

One job at a time, allowlisted actions only, errors go to `needs_staff`, no autonomous retries.

## Alerts (Member 4 publishes, Member 3 consumes)

`await app.alerts.send_alert(kind, session_id, message)`; kinds: `needs_staff`, `help_requested`, `repeated_failure`.

## Env flags

`ROBOT_MODE=mock|perceptron`, `VISION_MODE=mock|perceptron`, `GEMINI_API_KEY` (empty = keyword agent), `ELEVENLABS_API_KEY` (empty = browser voice), `MONGODB_URI` (empty = in-memory), `BACKBOARD_API_KEY` (set = voice through Backboard Realtime with automatic patient memory, falling back to direct Gemini if refused; empty = direct Gemini, care profile still used), `VOICE_TRANSPORT=backboard|gemini` (override).
