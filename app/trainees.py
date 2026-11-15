"""Persistence helpers for the trainee identity supplied by the common UI."""

from sqlalchemy.orm import Session

from app.db.models import Trainee


def upsert_trainee(db: Session, trainee_id: str, display_name: str) -> Trainee:
    """Keep the one local display-name record for a trainee ID current."""
    trainee = db.get(Trainee, trainee_id)
    if trainee is None:
        trainee = Trainee(trainee_id=trainee_id, display_name=display_name)
        db.add(trainee)
    elif trainee.display_name != display_name:
        trainee.display_name = display_name
    db.flush()
    return trainee
