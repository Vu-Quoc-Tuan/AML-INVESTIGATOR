# Investigation Control API

The frontend uses `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`.
The backend must allow that browser origin with
`CORS_ORIGINS=http://localhost:3000`. This trusted/local phase intentionally
has no authentication.

All commands below assume the backend is running on `localhost:8000`.

```bash
# Current mode, queue counts, and active run
curl -sS http://localhost:8000/api/v1/investigation-control

# Switch mode (rejected with 409 while a run is active)
curl -sS -X PUT http://localhost:8000/api/v1/investigation-control/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"MANUAL"}'

# Start the queue in MANUAL mode; response is 202 with a run_id
curl -sS -X POST http://localhost:8000/api/v1/investigation-control/runs \
  -H 'Content-Type: application/json' \
  -d '{"trigger":"MANUAL"}'

# Read one run and recent history
curl -sS http://localhost:8000/api/v1/investigation-control/runs/RUN_ID
curl -sS 'http://localhost:8000/api/v1/investigation-control/runs?limit=20'

# Read, save, and reset the optional global soft prompt
curl -sS http://localhost:8000/api/v1/investigation-control/configuration
curl -sS -X PUT http://localhost:8000/api/v1/investigation-control/configuration \
  -H 'Content-Type: application/json' \
  -d '{"soft_prompt":"Prioritize rapid pass-through indicators."}'
curl -sS -X PUT http://localhost:8000/api/v1/investigation-control/configuration \
  -H 'Content-Type: application/json' \
  -d '{"soft_prompt":""}'
```

AUTO mode does not create an in-process schedule. Configure an external cron
job for 02:00 Asia/Ho_Chi_Minh and send the matching trigger:

```cron
CRON_TZ=Asia/Ho_Chi_Minh
0 2 * * * curl -fsS -X POST http://localhost:8000/api/v1/investigation-control/runs -H 'Content-Type: application/json' -d '{"trigger":"AUTO"}'
```

Set mode to `AUTO` before that request. A trigger that does not match the
persisted mode, or a request made while another run is active, receives 409.
Active work is process-local; restarting FastAPI marks a persisted active run
`INTERRUPTED`. There is currently no cancel endpoint.
