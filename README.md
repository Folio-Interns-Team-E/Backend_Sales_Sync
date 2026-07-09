# AI Sales Pipeline Agent — Backend Architecture

## Context

This is the backend for an AI-powered sales pipeline platform: it handles team onboarding, lead management, AI-driven email and proposal generation, meeting scheduling, a knowledge base, an in-app chat agent, and (on this branch) Stripe-based subscription billing. It's built as an async FastAPI service backed by PostgreSQL, designed to be consumed by a separate frontend (deployed on Vercel) and to integrate with several third-party services — Grok (LLM), Apollo, Pinecone, Cal.com, Google, AWS S3, and Stripe.

---

## Tech Stack & Reasoning

| Layer | Choice | Why |
|---|---|---|
| Web framework | **FastAPI** | Async-native, automatic OpenAPI docs (`/docs`, `/redoc`), Pydantic-based validation out of the box — good fit for an API-only backend with many integrations. |
| Server | **Uvicorn** | Standard ASGI server for FastAPI; lightweight and production-ready. |
| ORM | **SQLAlchemy 2.0 (async)** | Modern async ORM API pairs naturally with FastAPI's async request handling — avoids blocking the event loop on DB calls. |
| DB driver | **asyncpg** (+ psycopg2-binary for tooling) | Fastest async Postgres driver available; psycopg2 kept around for Alembic/tooling that expects a sync driver. |
| Migrations | **Alembic** | De facto standard for SQLAlchemy schema versioning. |
| Validation/config | **Pydantic v2 + pydantic-settings** | Typed request/response schemas and typed environment-based settings in one consistent system. |
| Auth | **python-jose (JWT) + passlib/bcrypt** | Stateless auth via signed JWTs; bcrypt for one-way password hashing — a standard, well-audited combination. |
| Payments | **Stripe SDK** | Handles subscription checkout, webhooks, and lifecycle events without building payment logic from scratch. |
| File storage | **boto3 (AWS S3)** | Offloads file/asset storage (e.g. knowledge base documents) from the app server. |
| HTTP client | **httpx** | Async-native client for calling external APIs (Grok, Apollo, Cal.com, Google) without blocking. |
| Docs generation | **python-docx** | Used to generate proposal documents. |
| Dev tooling | **eralchemy2** | Auto-generates ERDs (`erd.png`, `erd1.png`) directly from SQLAlchemy models — keeps schema diagrams in sync with code. |

**Overall reasoning:** everything is async end-to-end (FastAPI → SQLAlchemy → asyncpg → httpx), so a single instance can hold many concurrent I/O-bound requests (LLM calls, third-party API calls, DB queries) without thread-per-request overhead. This matters here specifically because a lot of routes fan out to slow external services (Grok, Apollo, Google, Stripe).

---

## Project Structure

```
app/
├── main.py            # App entrypoint: router registration, CORS, global exception handlers
├── config.py           # Centralized settings (env-driven)
├── database.py         # Async engine, session factory, Base model
├── core/
│   ├── security.py     # JWT issuing/decoding, password hashing
│   └── s3.py            # S3 client/upload helpers
├── middleware/
│   └── auth_middleware.py  # get_current_user, role-based access guard
├── models/              # SQLAlchemy ORM tables
├── schemas/              # Pydantic request/response contracts
├── routers/              # Route definitions (thin — delegate to services)
└── services/             # Business logic + third-party integrations
migrations/               # Alembic migration scripts
```

This is a **layered architecture**: routers stay thin (parse request → call service → return), services hold the actual logic, models define persistence, and schemas define the wire format. This separation is what makes it easy to, say, swap how a proposal is generated without touching the route or the DB table.

### `models/` — persistence layer
One file per entity, each a SQLAlchemy `Base` subclass: `user`, `team`, `team_member` (join table with a `role` enum for RBAC), `lead` / `leads_pool`, `proposal`, `meeting`, `email`, `chat`, `knowledge_base`, `google_credentials`. Relationships are declared explicitly (`relationship(..., back_populates=..., cascade=...)`), so deleting a `Team` correctly cascades to its members and chat history rather than leaving orphaned rows.

### `schemas/` — validation & API contracts
Mirrors the router/model list (`auth`, `teams`, `leads`, `proposals`, `meetings`, `emails`, `knowledge_base`, `chat`, `onboarding`), plus a shared `common.py`. Keeping schemas separate from models means the DB shape and the public API shape can diverge on purpose (e.g. hiding internal fields, reshaping nested data) without touching the ORM.

### `routers/` — HTTP layer
One router per domain, each mounted in `main.py` with its own prefix/tags — `auth`, `teams`, `onboarding`, `leads`, `emails`, `meetings`, `proposals`, `knowledge_base`, `chat`, `integrations`, `billing`. Routers depend on `get_db` and `get_current_user`/`require_role` via FastAPI's `Depends`, keeping auth and DB session wiring declarative rather than manually repeated in each handler.

### `services/` — business logic
This is where the actual work happens, largely as one class per domain wrapping an `AsyncSession`:
- `auth_service` — signup/login, token issuance
- `teams_service`, `onboarding_service` — team creation, invites, ICP setup
- `leads_service` — lead ingestion/enrichment (Apollo)
- `grok_service`, `chat_service`, `chat_agents` — LLM-backed chat/agent logic
- `emails_service`, `gmail_service` — email generation and sending via Gmail
- `meetings_service`, `calcom_service` — scheduling via Cal.com
- `proposals_service` — AI-assisted proposal generation (python-docx output)
- `knowledge_base_service` — document ingestion, likely paired with Pinecone for retrieval
- `billing_service` — Stripe checkout/subscription lifecycle (see below)

### `core/` — cross-cutting utilities
`security.py` centralizes all JWT and password-hashing logic so it's never reimplemented per-feature. `s3.py` centralizes AWS upload logic similarly.

### `middleware/`
`auth_middleware.py` provides two dependency-injectable guards: `get_current_user` (decodes and validates the bearer JWT, loads the `User` row) and `require_role(*roles)` (checks the user's `TeamMember` role against an allow-list). This is FastAPI's idiomatic way to do auth — as reusable `Depends()` functions rather than a blanket middleware — which lets each route opt into exactly the access level it needs.

### `migrations/`
Alembic-managed; `env.py` and `versions/` track schema history so the DB can be migrated incrementally instead of relying on `create_all` in production.

---

## Key Design Decisions

**1. Async all the way down.** Every DB call, every external API call, and the route handlers themselves are `async def`. This is deliberate — a blocking call anywhere in this chain (e.g. a sync HTTP client) would stall the entire event loop, not just one request.

**2. Consistent API envelope.** Every response — success or failure — follows the same shape:
```json
{ "success": bool, "message": str, "data": ..., "error": ... }
```
This is enforced globally via exception handlers in `main.py` (`HTTPException`, `RequestValidationError`, and a catch-all `Exception` handler), so the frontend never has to guess the response shape based on status code alone. The catch-all handler also hides internal error details in production (`app_env != "development"`) while surfacing them in dev — a reasonable default for not leaking stack traces externally.

**3. Stateless JWT auth with role-based access control.** Auth state lives in the token, not server-side sessions, which fits a horizontally-scalable API. Authorization is layered on top via `TeamMember.role`, meaning permissions are scoped per-team rather than globally per-user — appropriate for a multi-tenant B2B product where one user can belong to multiple teams with different roles.

**4. Stripe as the source of truth for billing state, reconciled via webhooks.** `billing_service.py` creates the Stripe customer/checkout session, but the `Team.subscription_tier`/`subscription_status` fields are only actually updated by the `/billing/webhook` handler reacting to `checkout.session.completed`, `customer.subscription.deleted`, and `invoice.payment_failed` events — not by the checkout call itself. This is correct practice for Stripe integrations: the checkout redirect can't be trusted to confirm payment, only the signed webhook can. The webhook also verifies `stripe-signature` before trusting the payload, preventing forged billing events.

**5. Config validated at startup, not scattered `os.getenv` calls.** `config.py` defines one `Settings(BaseSettings)` class covering every credential and flag the app needs (DB, JWT, Grok, Apollo, Pinecone, AWS, Cal.com, Google, Stripe, CORS origins). Because it's a Pydantic model, missing required env vars fail fast at boot rather than surfacing as a runtime `KeyError` deep in a request.

**6. Connection resiliency on the DB engine.** `pool_pre_ping=True` and `pool_recycle=300` on the async engine guard against stale/dropped connections — a known issue with long-lived pools against managed Postgres (e.g. connections silently closed after idle timeouts).

**7. ERD generation from code, not hand-drawn docs.** `generate_erd.py` + `eralchemy2` produce `erd.png`/`erd1.png` directly from the SQLAlchemy models, so the schema diagram can't drift out of sync with the actual code the way a manually maintained diagram would.

---

## Best Practices Observed

- **Separation of concerns**: routers never touch the DB directly — they delegate to services, which own all DB and third-party logic.
- **Explicit password hygiene**: `ensure_bcrypt_password_size` guards against bcrypt's silent 72-byte truncation, raising a clear error instead of quietly hashing a truncated password.
- **Cascade rules on relationships** (e.g. `cascade="all, delete-orphan"` on `Team.members`) prevent orphaned rows when a parent entity is deleted.
- **Environment-driven CORS** rather than a wildcard, with explicit dev/prod frontend origins listed.
- **Webhook signature verification** before acting on any Stripe event.
- **Typed settings** over raw environment variable access throughout the codebase.

---

## Suggested Follow-Ups
A few things worth double-checking as this matures (not urgent, just flagged while reading through):
- `billing_service.create_checkout_session` currently hardcodes `success_url`/`cancel_url` to a placeholder domain — worth pulling from `settings` instead.
- Consider Alembic-only schema management in production rather than the `Base.metadata.create_all` call still present in `main.py`'s startup hook, to avoid the two drifting apart.
