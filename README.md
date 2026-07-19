# AML-INVESTIGATOR

Hệ thống multi-agent hỗ trợ tự động hóa phần điều tra sau khi một cảnh báo AML
được tạo (synthetic SHB-centric data).

## Docs

- [docs/README.md](docs/README.md) — mục lục tài liệu
- [docs/PROJECT.md](docs/PROJECT.md) — mục tiêu & phạm vi
- [docs/architecture.md](docs/architecture.md) — kiến trúc
- [backend/README-KAFKA.md](backend/README-KAFKA.md) — Kafka
- [backend/README-DETECTION.md](backend/README-DETECTION.md) — detection queue
- [backend/README.md](backend/README.md) — env & tests

## Layout

| Path | Nội dung |
|------|----------|
| `backend/` | FastAPI, agents, Kafka, detection, data |
| `frontend/` | Next.js UI (nhiều màn còn mock) |
| `docs/` | Product docs + superpowers specs/plans |

## Run FE + BE with Docker (local)

```bash
make up          # FE :3000 + BE 127.0.0.1:8000
make up-backend  # BE only (same as production CD)
make logs
make ps
make down
make down-clean  # stop + wipe SQLite volume
```

Env used by compose:

- `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000/api/v1`) — baked into FE at **build** time
- `CORS_ORIGINS` (default `http://localhost:3000`)

## Deploy (production)

```text
Browser → FE on Vercel (HTTPS)
       → https://aml-api.vutuan.indevs.in/api/v1  (Cloudflare Tunnel)
       → 127.0.0.1:8000 on self-hosted runner (Docker backend)
```

| Piece | How |
|-------|-----|
| **Backend** | Merge to `dev` / `main` → Actions → workflow **CD** → `development`. Runner: `self-hosted, Linux, X64, aml`. Only `docker compose up backend`. |
| **Frontend** | Actions → **CD Frontend (Vercel)** (manual or push to `main`/`dev` when `frontend/**` changes). |

Required GitHub config:

1. Environment **development** var `CORS_ORIGINS` — real Vercel origin(s), e.g. `https://aml-investigator.vercel.app,https://*.vercel.app,http://localhost:3000`
2. Secrets for FE: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
3. Optional repo/env var `NEXT_PUBLIC_API_BASE_URL` (default `https://aml-api.vutuan.indevs.in/api/v1`)

Backend compose contract (enforced by CD): publish **`127.0.0.1:8000:8000`**. Do not open `:8000` on `0.0.0.0`.
