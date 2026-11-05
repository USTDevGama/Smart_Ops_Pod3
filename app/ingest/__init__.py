"""Ingestion (owner: Dev A, Kedar): the trainee profile and the admin demand document.

PDF/DOCX/TXT parsing and OCR live here. Whatever is extracted is stored as JSON in the row's
`content` column and handed to the agent as it is. Code against app.llm.LLMClient only.
"""
