# Test suite structure

Tests are grouped by the product feature they primarily verify:

- `auth/` — authentication and account access
- `billing/` — checkout, subscriptions, cancellation, and webhooks
- `catalog/` — coverage mapping for the recommendation catalog
- `chat/` — conversations, messages, security, and resilience
- `contracts/` — API response and schema contracts
- `core/` — shared API behavior, security, performance, and observability
- `cross_feature/` — workflows that intentionally span multiple features
- `database/` — migrations and schema-drift checks
- `email/` — email APIs, integrations, and AI drafts
- `knowledge_base/` — uploads, assets, search, RAG, and provider failures
- `meetings/` — meeting lifecycle
- `proposals/` — templates, revisions, concurrency, and security
- `teams/` — team membership and authorization

`conftest.py` remains at the suite root because its fixtures are shared by all
features. File names describe the behavior under test; numbered batch names are
no longer used.
