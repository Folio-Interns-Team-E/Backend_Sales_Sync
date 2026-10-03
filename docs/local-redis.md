# Local Redis for development

On Windows with Ubuntu in WSL, an alternative to Docker is:

```powershell
wsl -d Ubuntu -u root -- apt-get update
wsl -d Ubuntu -u root -- apt-get install -y redis-server
wsl -d Ubuntu -u root -- service redis-server start
wsl -d Ubuntu -- redis-cli ping
```

Windows should reach this service at `redis://127.0.0.1:6379/0` through WSL localhost forwarding. Start the service again after a WSL shutdown if it is not already running. Verify connectivity from Windows before starting the backend.

If WSL exits when no interactive processes remain, keep this command running in a terminal during development:

```powershell
wsl -d Ubuntu -u root -- sh -lc 'service redis-server start && exec sleep infinity'
```

Allow `http://localhost:5173` and `http://127.0.0.1:5173` in the local backend `FRONTEND_ORIGINS` setting so browser authentication passes its origin check.

Start Docker Desktop, then run `docker compose up -d redis` from the backend folder. Only Redis is started; the configured PostgreSQL database is unchanged.

Set `REDIS_URL=redis://127.0.0.1:6379/0` in `backend/.env`, run `uv sync`, and restart the backend. REDIS_URL takes priority over the Upstash settings. Clear it to return to Upstash. Both providers support rate limits, OTP expiry, token revocation, and atomic password-recovery code consumption.

Redis is bound only to loopback and persists its data in the Compose redis_data volume. Check it with `docker compose exec redis redis-cli ping`. Stop it with `docker compose stop redis`. Do not remove the volume unless you intend to erase session revocations and recovery state.

The unauthenticated local connection is for development only. Production native Redis should use private networking, authentication, and TLS as appropriate. Email verification and password-recovery emails still require working Resend credentials; local Redis does not replace email delivery.
