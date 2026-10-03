# Account security activity

Settings displays successful password/Google/GitHub sign-ins, completed password resets, and Google/GitHub connections. History starts after deployment; old events are not reconstructed. Times are stored in UTC and displayed in the browser's timezone. A sign-in event means credential verification succeeded, not that the browser necessarily received its response.

`GET /auth/activity?limit=25&cursor=...` requires the existing bearer authentication. The account ID comes exclusively from that authentication dependency. Users cannot select another account or use team membership to read another person's history. Responses disable caching and expose only event ID, action, and timestamp. Pages use a timestamp/ID cursor, ordered newest first, with at most 100 events per request.

Records contain only account ID, event ID, a fixed action enum, and timestamp. No passwords, tokens, email addresses, IP addresses, user-agent strings, or free-form request payloads are stored. Mutations and their events commit in the same database transaction. A database write failure fails the action rather than silently losing its history. Normal session refresh is not treated as a fresh login.

Migration `20261003_security_events` follows `20261003_oauth_identities`. Apply migrations through the deployment process before running the updated application. Existing development startup can create missing tables. The migration adds only a new table and index.

This is account activity, not a complete enterprise audit system: failed login attempts, logout, team administration events, external log export, tamper-proof storage, and automated retention are not included. There are no history edit/delete API endpoints. Database administrators retain access; deletion of a user cascades to their events. Define the production retention policy before launch; records currently remain until account deletion or an authorized database maintenance operation.
