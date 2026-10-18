# Perceptron Robotics API — team notes

Source of truth: https://robotics.perceptron.inc/docs (OpenAPI: https://robotics.perceptron.inc/openapi.json).
These are our condensed notes for the SO-101 pipeline; check the live docs before relying on details.

- **Base URL:** `https://robotics.perceptron.inc`
- **Team auth:** `Authorization: Bearer $TEAM_API_KEY` for datasets, training, checkpoints, deployments and session grants. Keep it in `.env`, never commit it, and never send it to inference endpoints or signed upload URLs.
- **Inference auth:** `Authorization: Bearer $APPLICATION_SESSION_TOKEN` + `Modal-Authorization: Bearer $MODAL_SESSION_TOKEN` (both from the session grant).

## Pipeline

```
teleop recording -> dataset (HF or upload) -> validation -> training job -> checkpoint -> ready deployment
  -> session grant -> robot session -> predict loop -> delete session
```

## 1. Record demonstrations (LeRobot v2.0 / v2.1 / v3.0 export)

- 30 FPS
- Two RGB cameras, 640×480: `observation.images.side`, `observation.images.wrist`
- 6 state + 6 action values, in this order: `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`, `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`
- Arm joints in degrees; calibrated gripper 0–100
- Keep `meta/info.json`, episode metadata, data chunks, both video streams, original timestamps and episode boundaries together
- At least 1 training + 1 validation episode
- Sanity-check episode lengths, timestamps, frames and metadata before ingesting

## 2. Register a dataset — `POST /v1/datasets`

Send an `Idempotency-Key` header and reuse the same key when retrying.

- Hugging Face (public repo): `{"name": "...", "source_kind": "huggingface", "repo_id": "<org>/<repo>", "revision": "main"}`; ingestion is queued automatically.
- Direct upload: `{"name": "...", "source_kind": "upload"}`

Save the returned dataset `id`.

### Direct upload only

1. `POST /v1/datasets/{id}/uploads` with `{"files": [{"path", "size_bytes", "sha256"}]}` (lowercase hex SHA-256, up to 500 files per batch, `meta/info.json` required).
2. For each returned entry, `PUT` the raw bytes to its `url` using the returned `method` and exact `headers` (including `Content-Length`). URLs expire after 15 min. Don't attach the team key.
3. `POST /v1/datasets/{id}/finalize` once every file is uploaded.

### Check status

- `GET /v1/datasets/{id}`: poll until ready
- `GET /v1/datasets/{id}/validation`: review before training

## 3. Train — `POST /v1/jobs`

Check `GET /v1/capabilities` first for the supported backends, modes and limits.

```json
{"dataset_id": "<id>", "backend": "standard", "mode": "expert_only", "action_horizon": 30, "rtc_enabled": true, "steps": 1000}
```

Send an `Idempotency-Key`. Follow progress with `GET /v1/jobs/{id}`, `/logs` and `/metrics` (cursor-paged), and cancel with `POST /v1/jobs/{id}/cancel`.

### Limits from the OpenAPI schema (`/openapi.json`)

- `JobRequest`: `steps` 1–10,000; `action_horizon` 20 or 30; `mode` `expert_only` | `backbone_lora` | `full`; `backend` `standard` | `shared`; no extra fields.
- `DatasetRequest`: `name` 1–100 chars; only `name`, `source_kind`, `repo_id`, `revision`.
- `UploadFile`: `size_bytes` ≥ 1 (skip empty files), lowercase hex `sha256`, `path` ≤ 512 chars; 1–500 files per request.
- `SessionGrantRequest`: `ttl_seconds` ≤ 21,600; IDs match `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$`.
- Errors: `{"error": {"code", "message", "fields"}}`. Long-running calls may return `303` to a polling URL; follow it as-is.
- Response bodies aren't specified in the schema, and inference endpoints aren't in it at all; confirm field names with the contract and mentors.

## 4. Checkpoint & deployment

- `GET /v1/checkpoints/{id}`
- `GET /v1/deployments`: use only a deployment in `ready` state
- `GET /v1/deployments/{id}/contract`: save `contract_id`. It defines the cameras, state order, units, timing and how to interpret actions.

## 5. Session grant + robot session

1. `POST /v1/deployments/{id}/sessions` (team key) with `{"session_id": "robot-01", "ttl_seconds": 21600}`. This returns `endpoint_url`, `application_session_token`, `modal_session_token` and `session_id`.
2. `POST $ENDPOINT_URL/deployments/{id}/sessions` (session tokens) with `{"instruction": "pick up the tea box", "rtc_enabled": true, "contract_id": "<contract_id>"}`.

## 6. Predict loop — `POST $ENDPOINT_URL/sessions/{session_id}/predict`

Multipart body:

- `metadata` (JSON): `{"contract_id", "observation_id", "sequence", "timestamp_seconds", "state": [6 values], "image_encoding": "png"}`
- `side` and `wrist` image files

Increment `sequence` and the timestamp on every request, and execute the returned action chunk per the contract's timing. The optional `rtc` object takes `prior_chunk_id`, `prior_start_index`, `delay` and optionally `committed_actions` (one 6-value row per delayed step).

Other inference routes: `POST /sessions/{id}/reset` (new episode), `DELETE /sessions/{id}` (done), `GET /v1/inference/health`, `GET /v1/inference/healthz`, `GET /v1/inference/deployments/{id}/contract`.

Session state expires after inactivity. If that happens, get a fresh grant and create a new session rather than reusing stale state.

## Async polling

Long-running operations may return `303` with a `Location`. Poll only that same-origin HTTPS URL, with its query string exactly as returned.

## How this maps to ReMind

- The robot worker (see [SPEC.md](SPEC.md) §7) owns the session grant and predict loop. The orchestrator only sends it allowlisted `actionId`/`objectId` pairs, mapped to fixed instructions such as `"pick up the tea box and place it in the tray"`.
- No autonomous retries: if a predict call or the arm fails, the job is marked `failed` and the session goes to `needs_staff`.
- Delete the inference session when a ReMind session ends or Stop is pressed.
