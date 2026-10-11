# Workspace invite-code expiry

Invite codes expire 30 days after workspace creation or rotation. The migration gives existing workspaces a fresh 30-day window from migration time. Expired codes cannot be used to join a workspace or sent in new invitation emails. Admins can rotate the code from Team management, which invalidates old codes and starts a new 30-day window. Existing members retain access.

Managers can send invitations while a code is valid, but only admins can view or rotate the code. Expiry is checked by the backend; hiding or disabling controls in the frontend is only a convenience.
