# Password recovery

The login page links to `/forgot-password`. A user requests a recovery code by email, then pastes it with their new password. Codes expire after 15 minutes and are consumed atomically on use. Only their SHA-256 digests are stored as Redis keys. Request responses do not disclose whether an email is registered. Limits apply separately to the requesting IP and email address.

Required services: configure `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `RESEND_API_KEY`, and `FROM_EMAIL`. Recovery returns 503 when Redis is not configured. Email delivery requires an authorized sender in Resend. Automated tests mock these services; verify delivery in staging before release.

Endpoints:

- `POST /auth/password/request`: `{ "email": "person@example.com" }`
- `POST /auth/password/reset`: `{ "token": "emailed recovery code", "password": "new password" }`

New sessions contain a keyed fingerprint of the stored password hash. Both access-token authentication and refresh compare this fingerprint with the current user record. A password change therefore invalidates all previous sessions and outstanding recovery codes without a schema migration. Existing sessions issued before this release lack the fingerprint and users must log in again after deployment. Reset does not mark an unverified email as verified or automatically log the user in.

The IP limit uses the ASGI request client. Configure trusted proxy forwarding in the deployment so that public clients cannot spoof this value. Multiple users behind one address share its request limit.

Remaining identity work: MFA enrollment and recovery, organization SSO/SCIM, cross-site cookie configuration with CSRF protection, session/device management, and security audit events.
