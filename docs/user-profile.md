# Per-user profile

Company and job title are stored on each user account, not in shared browser storage or workspace membership. `GET /auth/profile` returns the authenticated account's name, email, company, and job title. `PATCH /auth/profile` updates name, company, and job title for that account; email is read-only and cannot be included in the update payload. A signed-in bearer session is required to make changes, and responses are marked `no-store`.

The migration adds nullable `company` and `job_title` columns. Existing browser-only values cannot be reliably attributed to an account and are intentionally not migrated; users should enter them once in Settings after deployment.
