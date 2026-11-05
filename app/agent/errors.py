class AgentError(Exception):
    """The agent could not produce a reply it is willing to stand behind.

    The chat service turns any exception from the engine into a 502 and saves nothing, so a
    failed reply never uses up one of the trainee's turns. Messages must never contain the
    trainee's text (it is sensitive data).
    """
