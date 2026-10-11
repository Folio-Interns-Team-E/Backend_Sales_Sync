# Workspace membership audit

The workspace audit trail records successful invitation emails, member joins, member role changes, member removals, workspace renames, and invite-code rotations. Admins and managers can view and export the trail. Membership, role, and rename events are committed in the same database transaction as the change; a failed commit leaves neither change nor event.

Invitation email is an external side effect. The audit event is committed only after the email provider accepts the send request, but delivery and the database commit cannot be atomic. If the database commit fails after acceptance, the recipient may still receive the invitation without an event. This needs an outbox if strict delivery/audit consistency is required.

Managers may remove sales reps, but not other managers or admins. Only admins can change roles or rotate invite codes. Audit rows store user IDs, not invitation email addresses or invite codes.
