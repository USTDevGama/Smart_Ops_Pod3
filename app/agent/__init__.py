"""Conversation agent (owner: Shubhra): how one client reply is produced.

The chat service talks to it only through `app.agent.engine.TurnEngine`. Code against
app.schemas (TurnOutput, Evaluation, PersonaConfig) and, if you need a model, app.llm.LLMClient.

The design, step by step, is in docs/agent-architecture.md. In short: one model call per turn
judges the trainee's answer, proposes how tough to be and writes the client's next message;
validate.py checks everything the model points at (the quote must be the trainee's own words);
the service clamps the level, saves the turn and decides when the chat ends. llm_engine.py ties
it together.
"""
