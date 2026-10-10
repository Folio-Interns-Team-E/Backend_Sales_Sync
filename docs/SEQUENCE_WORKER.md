# Sequence delivery worker

Run sequence delivery as a separate Railway service using the same repository and environment variables as the API.

- Start command: `python -m app.workers.sequence_worker`
- Required variables: `DATABASE_URL`, `DATABASE_SSL_MODE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Optional variables: `SEQUENCE_WORKER_INTERVAL_SECONDS=60`, `SEQUENCE_WORKER_BATCH_SIZE=20`, `LOG_LEVEL=INFO`

Only activate the worker after the API deployment has applied the latest Alembic migration. PostgreSQL row locking, daily limits, and idempotent delivery records prevent duplicate sends across replicas.

Failed Gmail requests retry up to three times with exponential backoff. Leads marked `Replied` stop before the next delivery when `stop_on_reply` is enabled.
