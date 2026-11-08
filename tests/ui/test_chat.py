"""The chat controller: the double tap, the bad moment, and the end of the chat."""

import httpx

from tests.ui.support import clients, output, stage
from ui.chat import ChatController, end_reason_text
from ui.persona_form import default_persona


class LosesTheFirstReply:
    """The message reaches the API and is saved, but the answer is lost on the way back."""

    def __init__(self, real):
        self.real = real
        self.lost = False

    def request(self, method, url, **kwargs):
        response = self.real.request(method, url, **kwargs)
        if str(url).endswith("/turns") and not self.lost:
            self.lost = True
            raise httpx.ReadTimeout("the connection dropped")
        return response


def open_chat(api, http=None, persona=None):
    admin, anna, profile_id = stage(api, persona=persona, http=http)
    return ChatController(anna, anna.start_session("verma-strict", profile_id)), admin


def trainee_turns(chat):
    return [t for t in chat.client.get_session(chat.id)["turns"] if t["role"] == "trainee"]


def test_a_message_gets_a_reply_and_updates_the_chat(api, engine):
    engine([output(level=2, reply="Be specific.")])
    chat, _ = open_chat(api)

    outcome = chat.send("We are looking at options.")

    assert outcome.ok and not outcome.ended and chat.pending is None
    assert chat.turns[-1]["content"] == "Be specific."
    assert (chat.level, chat.turns_used) == (2, 1)


def test_the_double_tap_saves_the_message_once(api, engine):
    scripted = engine([output(reply="The one reply.")])
    chat, _ = open_chat(api, http=LosesTheFirstReply(api.client))

    lost = chat.send("We will fix it by 9 June.")
    ticket = chat.pending.ticket
    assert not lost.ok and lost.retryable  # the app does not know the message was saved

    again = chat.retry()  # the same message, the same ticket

    assert again.ok and again.replayed
    assert chat.pending is None
    assert scripted.calls == 1  # the agent was not asked twice
    assert len(trainee_turns(chat)) == 1  # and nothing was saved twice
    assert ticket  # the ticket was kept for the retry


def test_when_the_agent_crashes_nothing_is_saved_and_a_retry_works(api, engine):
    scripted = engine([RuntimeError("agent crashed"), output(reply="Now it works.")])
    chat, _ = open_chat(api)

    failed = chat.send("Here is my answer.")
    ticket = chat.pending.ticket

    assert not failed.ok and failed.retryable
    assert chat.pending.content == "Here is my answer."
    assert trainee_turns(chat) == []  # the message was not counted
    assert chat.turns_used == 0

    again = chat.retry()

    assert again.ok and not again.replayed
    assert chat.pending is None and ticket
    assert chat.turns[-1]["content"] == "Now it works."
    assert scripted.calls == 2
    assert len(trainee_turns(chat)) == 1


def test_a_refused_message_is_not_kept_for_retry(api, engine):
    engine([output()])
    chat, _ = open_chat(api)
    chat.end()

    outcome = chat.send("Too late.")

    assert not outcome.ok and not outcome.retryable
    assert chat.pending is None
    assert "ended" in outcome.error


def test_an_empty_message_is_not_sent(api, engine):
    scripted = engine([output()])
    chat, _ = open_chat(api)
    assert not chat.send("   ").ok
    assert chat.pending is None and scripted.calls == 0


def test_a_second_message_waits_for_the_first_to_go_through(api, engine):
    engine([RuntimeError("agent crashed"), output()])
    chat, _ = open_chat(api)
    chat.send("First.")
    blocked = chat.send("Second.")
    assert not blocked.ok and blocked.retryable
    assert chat.pending.content == "First."


def test_the_chat_ends_at_the_message_limit_and_says_why(api, engine):
    persona = default_persona() | {"min_turns": 1, "max_turns": 1, "grace_turns": 0}
    engine([output()])
    chat, _ = open_chat(api, persona=persona)

    outcome = chat.send("My only answer.")

    assert outcome.ok and outcome.ended
    assert chat.ended and chat.end_reason == "turn_cap"
    assert "limit" in end_reason_text(chat.end_reason)


def test_ending_the_chat_marks_it_ended_by_the_trainee(api, engine):
    engine([output()])
    chat, _ = open_chat(api)
    chat.end()
    assert chat.ended and chat.end_reason == "trainee_ended"
    chat.end()  # harmless to repeat


def test_a_chat_can_be_opened_again_from_its_id(api, engine):
    engine([output(reply="Be specific.")])
    chat, _ = open_chat(api)
    chat.send("An answer.")

    _, anna = clients(api)
    reopened = ChatController(anna, anna.get_session(chat.id))

    assert [t["content"] for t in reopened.turns] == [t["content"] for t in chat.turns]
    assert reopened.turns_used == 1


def test_unknown_end_reasons_still_read_well():
    assert end_reason_text(None) == "The chat has ended."
    assert end_reason_text("something_new") == "The chat has ended."
