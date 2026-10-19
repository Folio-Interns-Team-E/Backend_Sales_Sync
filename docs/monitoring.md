# Production monitoring

SaleSync supports optional Sentry error and performance monitoring. The API still starts normally when no DSN is configured.

## Backend setup (Railway)

Create a Python/FastAPI project in Sentry and add these variables to both the API and sequence-worker services:

```env
SENTRY_DSN=https://...@...ingest.sentry.io/...
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=<git-commit-sha-or-release-name>
SENTRY_TRACES_SAMPLE_RATE=0.1
```

Start with a 10% trace sample rate and adjust it after observing traffic and Sentry usage. Exceptions are not sampled. Request bodies, query strings, cookies, authentication headers, API keys, email addresses, and IP addresses are not intentionally sent.

## Frontend setup (Vercel)

Create a JavaScript/React project in Sentry and configure:

```env
VITE_SENTRY_DSN=https://...@...ingest.sentry.io/...
VITE_SENTRY_ENVIRONMENT=production
VITE_SENTRY_RELEASE=<git-commit-sha-or-release-name>
VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
```

Redeploy after changing Vite environment variables because they are embedded at build time.

## Correlating an incident

API responses include `X-Request-ID`. Backend logs include the same value and Sentry events receive it as a tag. Use that ID to move from a user-facing failure to the exact request in Railway logs and Sentry.
