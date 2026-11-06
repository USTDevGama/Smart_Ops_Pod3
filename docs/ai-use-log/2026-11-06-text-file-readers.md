# 2026-11-06 - real file reading for profiles and demand documents (pdfplumber, python-docx)

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:**
  - the repo's own code and docs, and the team's design plan;
  - the made-up samples in `samples/` (including `Sample_Proposal_Store_Inventory_Dashboard.docx`, a fictional proposal), read locally to test the readers.
  - No secrets, no keys, no real trainee or client data, and nothing from the confidential seed pack.
- **What came back:** the real file reading in `app/ingest/` replacing the temporary placeholder: PDF with pdfplumber (`pdf_text.py`), DOCX with python-docx (`docx_text.py`), TXT directly (`extract.py`), a shared table-to-markdown helper, and `pipeline.py` that stores `{"text": "<markdown>"}` in `content`. Also tests, DOCX and PDF versions of the two samples (`scripts/make_samples.py`), and updated docs.
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:**
  - The paragraph-splitting threshold (line gap of 0.6 of a line height) and the scan check (under 20 characters and an image over 3% of the page) were tuned only on made-up PDFs; they have not been tried on real resumes or demand documents.
  - Two-column PDFs are read line by line across the columns, so the columns interleave.
  - DOCX text boxes, headers, footers, footnotes, content controls, tracked insertions and nested tables are not read (a resume that keeps the name or contact details in a header or text box loses them).
  - No live run of the worker against Redis has been done yet.
