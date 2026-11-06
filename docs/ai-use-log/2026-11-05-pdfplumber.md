# 2026-11-05 - move PDF and DOCX reading to pdfplumber and python-docx

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:**
  - the repo's own code and docs, and the team's design plan;
  - the made-up sample proposals in `samples/` (and the `SC01`-`SC03` files in that folder, which a teammate added), read locally to compare PDF readers and to test the new ones.
  - No secrets, no keys, no real trainee or client data, and nothing from the confidential seed pack.
- **What came back:** Docling, RapidOCR and Tesseract support removed; PDFs read with pdfplumber (`app/ingest/pdf_text.py`), DOCX with python-docx (`app/ingest/docx_text.py`), a shared table-to-markdown helper, and updated tests, samples and docs.
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:** the paragraph-splitting threshold (line gap of 0.6 of a line height) and the scan check (under 20 characters and an image over 3% of the page) were tuned only on made-up PDFs; they have not been tried on multi-column or real client-style documents.
