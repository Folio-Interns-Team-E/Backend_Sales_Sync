# Google Calendar meeting integration

SalesSync uses a separate per-user Google Calendar OAuth connection. Google sign-in and Gmail access do not grant Calendar access.

1. Enable **Google Calendar API** in the Google Cloud project used by `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
2. Add the exact redirect URI `https://api.salesync.world/integrations/google-calendar/callback` to that OAuth web client. Use the deployment's actual `OAUTH_PUBLIC_BASE_URL` if different.
3. Add `https://www.googleapis.com/auth/calendar.events` to the OAuth consent screen's data access scopes. Publish/verify the app as required for external users; add test users while the app is in testing.
4. Run the additive Alembic migration `20261011_google_calendar_meetings` before serving the new code. Test it on a Neon branch first and retain a backup.
5. Each organizer connects Google Calendar in Settings. Creating a meeting from a lead writes an event to the organizer's primary calendar and generates a unique Google Meet link. The prospect is **not** automatically invited; copy the link from the Meetings tab to share it.

Google Calendar meeting rescheduling is intentionally blocked until two-way update handling is implemented. SalesSync-created meetings are shown in SalesSync; unrelated Google Calendar events are not imported. Cancellation removes the Google event before updating the SalesSync record. If OAuth tokens are revoked, reconnect in Settings.
