"""Conversation agent (owner: Shubra): how one client reply is produced.

The chat service talks to it only through `app.agent.engine.TurnEngine`. Code against
app.schemas (TurnOutput, Evaluation, PersonaConfig) and, if you need a model, app.llm.LLMClient.
"""
