"""One chat, from the trainee's side. No Streamlit in here.

It carries the two safety rules of the story:
- The double tap: every message gets a ticket (the Idempotency-Key) before it is sent. If the
  connection hiccups, the same message is sent again with the same ticket and the API returns the
  saved reply instead of saving a second copy.
- The bad moment: if the API cannot get a reply, nothing was saved, so the message stays pending
  and can be sent again with the same ticket. A refusal (for example "the session has ended") is
  not retried.
"""

from dataclasses import dataclass

from ui.client import ApiError, PodCClient, new_ticket

END_REASONS = {
    "turn_cap": "The chat reached its message limit.",
    "trainee_ended": "You ended the chat.",
    "time_limit": "The chat reached its time limit.",
    "concerns_resolved": "The client's concerns were resolved.",
    "admin_ended": "An admin ended the chat.",
}


def end_reason_text(reason: str | None) -> str:
    return END_REASONS.get(reason or "", "The chat has ended.")


@dataclass
class Pending:
    """A message that has not gone through yet, with the ticket that protects it."""

    content: str
    ticket: str


@dataclass(frozen=True)
class Outcome:
    ok: bool
    error: str | None = None
    retryable: bool = False  # the message is still pending: send it again with the same ticket
    ended: bool = False
    replayed: bool = False  # the API had already saved this message and just returned the reply


class ChatController:
    def __init__(self, client: PodCClient, session: dict):
        self.client = client
        self.session = session  # the API's session detail, with its turns
        self.pending: Pending | None = None

    @property
    def id(self) -> str:
        return self.session["id"]

    @property
    def turns(self) -> list[dict]:
        return self.session["turns"]

    @property
    def ended(self) -> bool:
        return self.session["status"] == "ended"

    @property
    def end_reason(self) -> str | None:
        return self.session["end_reason"]

    @property
    def level(self) -> int:
        return self.session["level"]

    @property
    def turns_used(self) -> int:
        return self.session["turns_used"]

    @property
    def max_turns(self) -> int:
        return self.session["max_turns"]

    def refresh(self) -> None:
        self.session = self.client.get_session(self.id)

    def send(self, text: str) -> Outcome:
        text = text.strip()
        if not text:
            return Outcome(False, "Type a message first.")
        if self.pending is not None:
            return Outcome(False, "The last message has not gone through yet.", retryable=True)
        self.pending = Pending(text, new_ticket())
        return self._attempt()

    def retry(self) -> Outcome:
        """Send the pending message again with the same ticket."""
        if self.pending is None:
            return Outcome(False, "There is nothing to send again.")
        return self._attempt()

    def discard_pending(self) -> None:
        self.pending = None

    def end(self) -> None:
        self.session = self.client.end_session(self.id)
        self.pending = None

    def _attempt(self) -> Outcome:
        pending = self.pending
        try:
            result = self.client.send_turn(self.id, pending.content, pending.ticket)
        except ApiError as exc:
            if exc.retryable:
                return Outcome(False, exc.detail, retryable=True)  # keep it pending
            self.pending = None  # refused: sending the same message again would be refused too
            self._refresh_quietly()
            return Outcome(False, exc.detail)
        self.pending = None
        self._refresh_quietly()
        return Outcome(True, ended=result.done["ended"], replayed=result.done["replayed"])

    def _refresh_quietly(self) -> None:
        try:
            self.refresh()
        except ApiError:
            pass  # the message went through; the next refresh will catch up
