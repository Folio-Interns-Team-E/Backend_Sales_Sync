# Railway deployment and domain cutover

Status: deployment preparation only. No Railway project, subscription, production variables, database migration, or DNS records have been changed by this work.

## Recommended layout

- Website: `https://example.com` on the frontend host.
- Customer application: `https://app.example.com` on the frontend host.
- FastAPI: `https://api.example.com` on Railway.
- Redis: private Railway service with persistent storage.
- PostgreSQL: retain the existing database for the first backend move unless a separate data migration is approved. Place API and databases near one another; Singapore is a candidate region for Pakistan, but measure actual latency.

Replace example.com with the purchased domain. Keep the frontend provider unchanged for this backend migration. The paid plan is billed for aggregate resource usage, not a fixed unlimited hosting fee. Disable Serverless/app sleeping for an always-running customer API. Start with one replica, monitor memory/CPU and request latency, and size after load tests.

## Create the backend service

1. In a company-controlled Railway workspace, select the paid plan and billing owner. Set usage notifications.
2. Create a project/environment, then connect the `Backend_Sales_Sync` GitHub repository. This is a separate backend repo: use repository root `/`, not `/Backend_Sales_Sync`.
3. Use the root Dockerfile. It installs frozen runtime dependencies, excludes local environment files, and runs as an unprivileged user. Leave the start-command override empty; its command `python -m app.serve` reads Railway's PORT and binds to 0.0.0.0.
4. Set the healthcheck path to `/ready` and allow 120 seconds for deployment startup. `/health` remains a process liveness endpoint; `/ready` checks PostgreSQL, the authentication tables, and Redis. Railway deployment healthchecks are not a replacement for ongoing external uptime monitoring.
5. Add a Redis service with persistence. Reference its private connection URL in the backend's REDIS_URL. Do not copy `redis://127.0.0.1:6379/0` from the laptop.
6. Configure variables below, prepare/check the database schema, and deploy to a temporary Railway domain before switching customer traffic.

## Required variables

```env
APP_ENV=production
DATABASE_URL=<existing hosted PostgreSQL URL or Railway variable reference>
DATABASE_SSL_MODE=auto
REDIS_URL=${{Redis.REDIS_URL}}
JWT_SECRET=<a securely generated production secret of at least 32 characters>
JWT_ISSUER=sales-sync-api
JWT_AUDIENCE=sales-sync-web
FRONTEND_ORIGINS=["https://app.example.com","https://example.com"]
BACKEND_URL=https://api.example.com
OAUTH_PUBLIC_BASE_URL=https://api.example.com
OAUTH_FRONTEND_URL=https://app.example.com
REFRESH_COOKIE_SAMESITE=lax
DB_ENCRYPTION_KEY=<the existing encryption key if migrating existing encrypted records>
```

Railway service names in references must match the actual project (`Redis` above is an example). Native postgres:// and postgresql:// URLs are translated to asyncpg by the application. SSL defaults to required outside development/test; use a provider-appropriate verification mode and CA configuration for stronger certificate validation. Do not disable SSL for an externally hosted database. Keep database and Redis endpoints private where possible.

Set Google/GitHub credentials, RESEND_API_KEY, verified FROM_EMAIL, and the existing file storage, AI, Gmail, and billing integration variables needed by the enabled product features. Never paste secrets into GitHub or a frontend VITE_ variable. Preserve DB_ENCRYPTION_KEY when retaining existing encrypted integration records. Rotating JWT_SECRET signs users out.

Before launch verify Railway's current trusted-proxy topology and set FORWARDED_ALLOW_IPS accordingly; otherwise clients may share an edge IP for rate limiting. Do not set it to `*` on a directly reachable, untrusted service. Standard access logs are disabled so OAuth callback codes are not written to request URL logs.

## Database safety gate

Production startup does not create or alter tables. The historical first migration adds columns to an already existing `teams` table, so `alembic upgrade head` is NOT a fresh-database bootstrap. Some historical migrations are destructive. There is intentionally no automatic pre-deploy migration command until this history and the target database are reconciled.

For the existing database, verify required tables, current revision and schema on a backup/clone. Apply only the reviewed missing migrations. Do not blindly stamp head or replay old migrations. A failing `/ready` with `database=false` can indicate missing auth tables even if the network connection works.

For a move to Railway PostgreSQL: back up the source, test restoring into a new target, verify row counts and schema, preserve encryption keys, stop writes during final synchronization, switch DATABASE_URL, test, and retain the source for rollback. Do not delete the old database. An entirely empty production database needs a separately reviewed baseline/initialization plan before launch.

## Domain and OAuth

Add `api.example.com` as a custom domain on the API service. Copy the exact DNS records Railway displays into the registrar/DNS dashboard; do not guess the CNAME destination. Railway provisions TLS after DNS validation. Point `app.example.com` and the root website at the frontend host, not at the API service.

Set the frontend's production `VITE_API_URL=https://api.example.com` and rebuild/redeploy. The frontend dev server continues to use the local /api proxy. HTTPS app.example.com and api.example.com share a site, so SameSite=lax is appropriate. Unrelated temporary hosting domains may need SameSite=none; third-party cookie restrictions still apply, especially to social-login state cookies. Complete the custom domain setup before production OAuth testing.

Register these exact production redirect URIs in separate production OAuth apps:

- Google: `https://api.example.com/auth/oauth/google/callback`
- GitHub: `https://api.example.com/auth/oauth/github/callback`
- Gmail integration, if enabled: `https://api.example.com/integrations/gmail/callback`

Configure the production Google consent screen and permitted audience. Update billing webhooks and return URLs if enabled. Verify the sender domain with the email provider.

## Cutover checklist

Test login/logout, session refresh, password recovery delivery, both social providers, account linking, tenant isolation, uploads, billing, and security activity on staging. Confirm database backups and a restore test, Redis persistence, application monitoring, and spending alerts. Switch the frontend API URL/DNS only after these pass. Keep the previous service available until the new deployment is verified; do not run independent old and new Redis-backed auth stacks against customer traffic without planning session invalidation.

Sources: [Railway FastAPI](https://docs.railway.com/guides/fastapi), [healthchecks](https://docs.railway.com/deployments/healthchecks), [domains](https://docs.railway.com/networking/domains/working-with-domains), [regions](https://docs.railway.com/deployments/regions), [pricing](https://railway.com/pricing).
