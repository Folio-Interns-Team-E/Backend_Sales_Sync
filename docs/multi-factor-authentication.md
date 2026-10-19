# Multi-factor authentication

SaleSync supports optional TOTP multi-factor authentication for password sign-in. Users configure it from **Settings → Multi-factor authentication** with any RFC 6238 authenticator app.

Enrollment secrets are encrypted with `DB_ENCRYPTION_KEY`. Pending enrollment data and five-minute login tickets live in Redis and are never stored in browser storage. Recovery codes are shown once, stored only as keyed SHA-256 digests, and consumed after one successful use. Login and enrollment verification are rate-limited.

Disabling MFA requires the current password plus an authenticator or recovery code. It increments the account session version, invalidating every existing access and refresh token, and signs the current browser out. Enrollment, MFA login, disablement, and recovery-code regeneration appear in the account security activity.

Google and GitHub sign-in continue to rely on the provider's authentication controls; local TOTP is applied to SaleSync password sign-in. Organization-enforced identity-provider MFA belongs in the future SSO/SAML feature.

## Deployment

1. Confirm `DB_ENCRYPTION_KEY` is a stable Fernet key and Redis is persistent and reachable.
2. Rehearse migration `20261016_account_mfa` on a Neon branch created from production.
3. Deploy the API and run `alembic upgrade head` through the existing pre-deploy process.
4. Verify `/ready` reports both dependencies healthy.
5. Enroll a staging user, sign out, verify authenticator and recovery-code login, regenerate recovery codes, then disable MFA and confirm prior sessions no longer refresh.

Never rotate `DB_ENCRYPTION_KEY` without re-encrypting existing MFA and provider credentials first. Losing the key makes enrolled authenticator secrets unreadable.
