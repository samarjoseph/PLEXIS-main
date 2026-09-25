"""Early Access ORM model."""
import uuid
from sqlalchemy import Column, String, DateTime, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from db.base import Base

class EarlyAccessSubmission(Base):
    __tablename__ = "early_access_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False, index=True)
    role = Column(String(100), nullable=True)
    selected_features = Column(ARRAY(String), nullable=True)
    idea = Column(Text, nullable=True)
    status = Column(String(20), default="new", nullable=False) # new, reviewed, contacted
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<EarlyAccessSubmission id={self.id} email={self.email}>"
