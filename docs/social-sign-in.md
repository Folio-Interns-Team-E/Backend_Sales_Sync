# Google and GitHub sign-in

The login page offers both providers. New accounts require a verified provider email. Existing users sign in with their current method and connect a provider from Settings. Matching email addresses never silently link accounts. Provider subject IDs are stored in oauth_identities; provider access tokens are used to fetch identity information and are not persisted. Social-only accounts have an unguessable random password and can use password recovery to establish a password.

## Local setup

Set these server-only values in backend/.env (never commit real secrets):

```env
GOOGLE_LOGIN_CLIENT_ID=
GOOGLE_LOGIN_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
OAUTH_PUBLIC_BASE_URL=http://localhost:5173/api
OAUTH_FRONTEND_URL=http://localhost:5173
```

Create a Google OAuth client of type Web application, configure its consent screen, and add test users when the consent screen is in testing. Register this exact authorized redirect URI:

`http://localhost:5173/api/auth/oauth/google/callback`

Create a GitHub OAuth App (Settings → Developer settings → OAuth Apps), with homepage `http://localhost:5173` and callback:

`http://localhost:5173/api/auth/oauth/github/callback`

Restart the backend after saving settings. Use localhost consistently, not 127.0.0.1, when testing these registered callbacks. Credentials for Gmail integration remain independent. Unconfigured providers show a friendly error when clicked.

## Deployment

Apply migration `20261003_oauth_identities` on a database already at `6f2efeef68f7`. Review the existing migration history before upgrading older databases. Development startup also creates the new table via the project's existing create_all behavior. Never stamp migration revisions without checking the schema.

Set OAUTH_PUBLIC_BASE_URL to the public API base (including any /api proxy prefix), OAUTH_FRONTEND_URL to the exact frontend origin, and include that origin in FRONTEND_ORIGINS. Register the corresponding HTTPS callbacks with both providers. Use the same API origin for starting the flow and receiving the callback so the browser-binding cookie is available. Same-site API hosting avoids third-party cookie restrictions. No access or refresh tokens are passed in redirect URLs.

State is stored for ten minutes in Redis and consumed once, bound to provider and browser. Authorization uses PKCE S256. Session establishment uses the existing HttpOnly refresh cookie. Password changes invalidate pending linking flows. An already-linked provider cannot be reassigned to another user.

## Verification

Test each provider with a new account, repeat sign-in, cancellation, expired callbacks, and linking from Settings. Existing email/password accounts must be refused automatic linking. Real sign-in requires credentials and user consent; automated tests mock provider responses.

References: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [GitHub OAuth authorization](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).
