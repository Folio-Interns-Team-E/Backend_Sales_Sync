# Request rate limiting

SaleSync protects security-sensitive and provider-backed operations with Redis fixed-window limits. Limiter keys contain only truncated SHA-256 identity hashes; raw IP addresses, user IDs, and workspace IDs are not stored in keys.

## Protected operations

| Area | Scope | Limit |
| --- | --- | --- |
| Login | IP | 10/minute |
| Registration | IP | 5/hour |
| OTP request and verification | IP | 5/15 minutes |
| Password recovery | IP | 5/15 minutes |
| Session refresh | IP | 30/minute |
| OAuth start, link, and callback | IP or user | 20/5 minutes |
| AI chat | User and workspace | 30/minute |
| Email sending | User and workspace | 30/minute |
| Email drafting | User and workspace | 60/minute |
| Lead discovery and generation | User and workspace | 20/hour |
| CSV lead import | User and workspace | 10/hour |

Successful protected responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`. Rejected requests return HTTP 429 and `Retry-After`.

## Availability behavior

- Production and staging fail closed with HTTP 503 if Redis is unavailable. This prevents authentication and paid-provider abuse during an infrastructure incident.
- Development and test environments fail open and log a warning so local work is not blocked when Redis is intentionally absent.

## Proxy configuration

`RATE_LIMIT_TRUST_PROXY_HEADERS` defaults to `false`. Set it to `true` only when the API is reachable exclusively through a trusted reverse proxy that replaces client-supplied forwarding headers. Railway deployments should enable it after confirming direct service access is disabled. When enabled, `CF-Connecting-IP` is preferred, followed by the first `X-Forwarded-For` address.
