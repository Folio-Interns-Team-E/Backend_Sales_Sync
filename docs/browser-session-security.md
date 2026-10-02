# Browser session security

All state-changing `/auth/*` requests require `X-SalesSync-Request: 1`. When an Origin header is present, it must exactly match an entry in `FRONTEND_ORIGINS`. This also protects login, logout, and refresh against cross-site requests. Native API clients must include the custom header; they may omit Origin. Browser clients cannot add the header cross-origin without a successful CORS preflight. Keep the origin allowlist limited to trusted applications. CORS middleware must continue to allow credentials and this header.

Refresh cookies are HttpOnly, host-only, and use Path=/ so both `/auth/*` and a reverse proxy's `/api/auth/*` receive them. Login/refresh and logout expire the previous Path=/auth cookie. Existing users whose browser cannot send the old cookie through a proxy must log in once after this update.

Local HTTP development uses `REFRESH_COOKIE_SAMESITE=lax`. For frontend and backend hosted on different sites over HTTPS, use `REFRESH_COOKIE_SAMESITE=none` and a non-development APP_ENV. The API sets Secure outside development. Browsers may still block third-party cookies; hosting the API under the frontend's site is preferable when that happens.

Deploy the frontend header change and backend protection together. Session renewal still requires a functioning Redis service; this update does not bypass the outstanding Redis configuration problem.
