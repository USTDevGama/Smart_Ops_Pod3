from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import CurrentUser, require_role
from app.schemas.enums import Role

app = FastAPI()

# Build the dependency once at module level (keeps ruff's B008 check happy).
admin_required = require_role(Role.ADMIN)


@app.get("/admin-only")
def admin_only(user: CurrentUser = Depends(admin_required)) -> dict:
    return {"user": user.user_ref}


client = TestClient(app)


def _headers(role: str) -> dict:
    headers = {"X-Dev-User": "tester", "X-Dev-Role": role}
    if role == "trainee":
        headers["X-Dev-Trainee-Id"] = "T-TEST"
    return headers


def test_admin_allowed():
    assert client.get("/admin-only", headers=_headers("admin")).status_code == 200


def test_trainee_forbidden():
    assert client.get("/admin-only", headers=_headers("trainee")).status_code == 403


def test_missing_or_unknown_role_is_unauthorised():
    assert client.get("/admin-only").status_code == 401
    assert client.get("/admin-only", headers=_headers("wizard")).status_code == 401
