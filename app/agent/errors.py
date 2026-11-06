class AgentError(Exception):
    """The agent could not produce a reply it is willing to stand behind.

    The chat service turns any exception from the engine into a 502 and saves nothing, so a
    failed reply never uses up one of the trainee's turns. Messages must never contain the
    trainee's text, the documents or the model's output (all of it is sensitive data): reason
    codes only.
    """


class MalformedReply(AgentError):
    """The model answered, but not in a form we can use. The engine retries once, then gives up.

    `code` is a short fixed reason (for example "quote_not_in_answer"); it never contains text
    from the conversation, so it is safe to log and to show to the model on the retry.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
