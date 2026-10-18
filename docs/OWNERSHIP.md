# Code ownership

Each member owns disjoint folders, so you can work in parallel without merge conflicts. Edit only your own folders. If you need a change in someone else's, ask them or open a small PR they review. Roles are described in [REQUIREMENTS.md](REQUIREMENTS.md#7-team-responsibilities).

| Member | Role | Owns (only edit these) | Tests |
| --- | --- | --- | --- |
| 1 | Robot and policy | `robot_worker/` (`worker/`, `scripts/`, `poses.json`, `README.md`) | run on hardware, plus mock mode |
| 2 | Vision and game logic | `backend/app/games/`, `backend/app/vision/` | `backend/tests/test_reorder.py`, `test_vision.py` |
| 3 | Agent and orchestration | `backend/app/main.py`, `agent.py`, `catalog.py`, `models.py`, `db.py`, `config.py`, `robot_client.py`, `backend/tests/test_flow.py` | `test_flow.py` |
| 4 | Frontend, alerts, demo | `frontend/`, `backend/app/alerts/`, `docs/design/` (Figma exports), pitch and demo script | manual |

Shared files (change through a PR everyone reviews): `docs/CONTRACTS.md`, `.env.example`, `README.md`, `docs/REQUIREMENTS.md`.

## How the pieces talk (so nobody blocks anybody)

All cross-member calls go through the interfaces in [CONTRACTS.md](CONTRACTS.md). Every interface already has a **mock**, so build against it first:

| You need | Use this until the real thing lands |
| --- | --- |
| Robot (M3, M4) | `ROBOT_MODE=mock` in `robot_worker/` |
| Vision (M3, M4) | `VISION_MODE=mock`; `POST /api/vision/check` accepts `mockOrder` |
| Game rules (M3) | import `app.games.reorder` (`shuffled`, `evaluate`) |
| Backend API (M4) | run `backend/` locally; endpoints are in CONTRACTS.md |
| Alerts (M3) | `from app.alerts import send_alert` (logs only until Photon is wired) |

## Git workflow

- Branch per person/feature: `m1/policy`, `m2/vision`, `m3/agent`, `m4/ui`. Open small PRs into `main`; rebase often.
- Never commit `.env` or secrets. Never force-push `main`.
- `GitHub CODEOWNERS` is in `.github/CODEOWNERS` (fill in usernames, see the file).
