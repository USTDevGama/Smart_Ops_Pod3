"""A small client for the Pod C API. No Streamlit in here, so tests can drive the real app with it.

Every method maps to one endpoint of the API contract. Failures raise `ApiError`; `retryable`
tells the caller whether trying again with the same request makes sense (the API could not be
reached, or the server failed), as opposed to a refusal such as "the session has ended".
"""

import json
import uuid
from dataclasses import dataclass

import httpx

DEFAULT_URL = "http://localhost:8000"


class ApiError(Exception):
    """The API refused, failed or could not be reached. `status` 0 means it was not reached."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.status == 0 or self.status >= 500


@dataclass(frozen=True)
class Upload:
    row: dict
    reused: bool  # the same file again: the API returned the earlier record (HTTP 200, not 202)


@dataclass(frozen=True)
class TurnResult:
    reply: dict  # the client's message (a turn)
    done: dict  # trainee_turn_id, persona_turn_id, level, turns_used, ended, end_reason, replayed


def new_ticket() -> str:
    """A receipt for one message (the Idempotency-Key): the same ticket never saves twice."""
    return uuid.uuid4().hex


def error_detail(response: httpx.Response) -> str:
    """The API's error as readable text. Its shape is {"type", "title", "status", "detail"}."""
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code} {response.reason_phrase}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        lines = []
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                where = ".".join(str(p) for p in item.get("loc", []) if p not in ("body",))
                lines.append(f"{where}: {item['msg']}" if where else str(item["msg"]))
            else:
                lines.append(str(item))
        return "\n".join(lines)
    if isinstance(body, dict) and body.get("title"):
        return str(body["title"])
    return f"{response.status_code} {response.reason_phrase}"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Server-sent events as (event name, decoded JSON data), in order."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].lstrip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


class PodCClient:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        user: str = "anna",
        role: str = "trainee",
        http: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.user = user
        self.role = role
        self._http = http or httpx.Client(base_url=base_url, timeout=60)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.base_url, self.user, self.role)

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"X-Dev-User": self.user, "X-Dev-Role": self.role, **kwargs.pop("headers", {})}
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            reason = f"cannot reach the API at {self.base_url} ({type(exc).__name__})"
            raise ApiError(0, reason) from None
        if response.status_code >= 400:
            raise ApiError(response.status_code, error_detail(response))
        return response

    def _json(self, method: str, path: str, **kwargs):
        return self._call(method, path, **kwargs).json()

    # --- ops ---------------------------------------------------------------------------------

    def ready(self) -> bool:
        """Whether the API is up and reaches its database. Short timeout: it runs on every page."""
        try:
            self._call("GET", "/readyz", timeout=3)
        except ApiError:
            return False
        return True

    def meta(self) -> dict:
        return self._json("GET", "/api/v1/meta", timeout=3)

    # --- settings (admin) --------------------------------------------------------------------

    def list_keys(self, kind: str) -> list[dict]:
        return self._json("GET", f"/api/v1/admin/config/{kind}")

    def get_version(self, kind: str, key: str, version_no: int) -> dict:
        return self._json("GET", f"/api/v1/admin/config/{kind}/{key}/versions/{version_no}")

    def create_persona(self, key: str, config: dict) -> dict:
        return self._json(
            "POST", "/api/v1/admin/config/persona", json={"key": key, "config": config}
        )

    def new_persona_version(self, key: str, config: dict | None = None) -> dict:
        body = {"config": config} if config is not None else None
        return self._json("POST", f"/api/v1/admin/config/persona/{key}/versions", json=body)

    def edit_persona_draft(self, key: str, version_no: int, config: dict) -> dict:
        path = f"/api/v1/admin/config/persona/{key}/versions/{version_no}"
        return self._json("PUT", path, json={"config": config})

    def publish_persona(self, key: str, version_no: int) -> dict:
        path = f"/api/v1/admin/config/persona/{key}/versions/{version_no}/publish"
        return self._json("POST", path)

    def import_scenarios(self, payload: dict) -> dict:
        return self._json("POST", "/api/v1/admin/scenarios/import", json=payload)

    def list_personas(self) -> list[dict]:
        return self._json("GET", "/api/v1/personas")

    # --- profiles (the trainee's resume) -----------------------------------------------------

    def upload_profile(self, filename: str, data: bytes) -> Upload:
        response = self._call("POST", "/api/v1/profiles", files={"file": (filename, data)})
        return Upload(response.json(), reused=response.status_code == 200)

    def list_profiles(self) -> list[dict]:
        return self._json("GET", "/api/v1/profiles")

    def get_profile(self, profile_id: str) -> dict:
        return self._json("GET", f"/api/v1/profiles/{profile_id}")

    def delete_profile(self, profile_id: str) -> None:
        self._call("DELETE", f"/api/v1/profiles/{profile_id}")

    # --- demand document (admin) -------------------------------------------------------------

    def upload_demand(self, filename: str, data: bytes) -> Upload:
        response = self._call("POST", "/api/v1/admin/demand", files={"file": (filename, data)})
        return Upload(response.json(), reused=response.status_code == 200)

    def list_demands(self) -> list[dict]:
        return self._json("GET", "/api/v1/admin/demand")

    def get_demand(self, demand_id: str) -> dict:
        return self._json("GET", f"/api/v1/admin/demand/{demand_id}")

    def delete_demand(self, demand_id: str) -> None:
        self._call("DELETE", f"/api/v1/admin/demand/{demand_id}")

    # --- sessions ----------------------------------------------------------------------------

    def start_session(self, persona_key: str, profile_id: str) -> dict:
        body = {"persona_key": persona_key, "profile_id": profile_id}
        return self._json("POST", "/api/v1/sessions", json=body)

    def list_sessions(
        self, status: str | None = None, trainee_ref: str | None = None
    ) -> list[dict]:
        params = {k: v for k, v in {"status": status, "trainee_ref": trainee_ref}.items() if v}
        return self._json("GET", "/api/v1/sessions", params=params)

    def get_session(self, session_id: str) -> dict:
        return self._json("GET", f"/api/v1/sessions/{session_id}")

    def end_session(self, session_id: str) -> dict:
        return self._json("POST", f"/api/v1/sessions/{session_id}/end")

    def send_turn(self, session_id: str, content: str, ticket: str) -> TurnResult:
        """Send one message. The same `ticket` again returns the saved reply, saving nothing new."""
        response = self._call(
            "POST",
            f"/api/v1/sessions/{session_id}/turns",
            json={"content": content},
            headers={"Idempotency-Key": ticket},
        )
        events = dict(parse_sse(response.text))
        if "message" not in events or "done" not in events:
            raise ApiError(502, "the reply was cut off")  # safe to retry with the same ticket
        return TurnResult(reply=events["message"], done=events["done"])

    # --- the report of an ended chat ---------------------------------------------------------

    def report_status(self, session_id: str) -> dict:
        """`state` is not_ended, generating or ready; admins get `can_download` once ready."""
        return self._json("GET", f"/api/v1/sessions/{session_id}/report")

    def request_report(self, session_id: str) -> dict:
        """Make sure the report is being generated (safe to repeat). `queued` says whether this
        call sent a new job; the API does not send a second one while the first is still running."""
        return self._json("POST", f"/api/v1/sessions/{session_id}/report")

    def download_report(self, session_id: str, fmt: str) -> bytes:
        """The report file (`pdf`, `html` or `md`). Admins only."""
        return self._call("GET", f"/api/v1/admin/sessions/{session_id}/report/{fmt}").content
