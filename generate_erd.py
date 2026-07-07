from eralchemy2 import render_er
from app.database import Base

# Import all models so SQLAlchemy registers them
from app.models import user, team, team_member, lead, meeting, proposal, chat

render_er(Base.metadata, "erd.png")