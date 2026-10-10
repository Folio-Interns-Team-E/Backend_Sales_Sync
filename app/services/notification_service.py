from app.models.notification import Notification


def create_notification(db, team_id, user_id, kind: str, title: str, body: str, link: str | None = None):
    notification = Notification(
        team_id=team_id,
        user_id=user_id,
        kind=kind[:40],
        title=title[:160],
        body=body[:500],
        link=link[:255] if link else None,
    )
    db.add(notification)
    return notification
