import pytest

from app.ingest.validate import (
    UploadRejected,
    check_content,
    check_size,
    display_name,
    file_type_for,
)
from app.schemas.enums import FileType
from tests.ingest_fixtures import make_docx, make_pdf


@pytest.mark.parametrize(
    "name, expected",
    [("plan.PDF", FileType.PDF), ("plan.docx", FileType.DOCX), ("notes.txt", FileType.TXT)],
)
def test_extension_decides_type(name, expected):
    assert file_type_for(name) is expected


@pytest.mark.parametrize("name", ["plan.exe", "plan", "plan.pdf.exe", "plan.doc"])
def test_other_extensions_are_refused(name):
    with pytest.raises(UploadRejected):
        file_type_for(name)


def test_real_pdf_and_docx_pass_content_checks():
    check_content(make_pdf(["hello"]), FileType.PDF)
    check_content(make_docx([("", "hello")]), FileType.DOCX)


def test_renamed_exe_as_pdf_is_refused():
    with pytest.raises(UploadRejected):
        check_content(b"MZ\x90\x00 not a pdf", FileType.PDF)


def test_zip_that_is_not_a_docx_is_refused():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hi")
    with pytest.raises(UploadRejected):
        check_content(buffer.getvalue(), FileType.DOCX)


def test_binary_is_refused_as_txt_but_text_passes():
    with pytest.raises(UploadRejected):
        check_content(b"abc\x00def", FileType.TXT)
    check_content("Budget: 400,000 €".encode(), FileType.TXT)


def test_empty_and_oversized_files_are_refused():
    with pytest.raises(UploadRejected, match="empty"):
        check_size(b"", 10)
    with pytest.raises(UploadRejected, match="larger"):
        check_size(b"x" * 11, 10)
    check_size(b"x" * 10, 10)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\plan.docx", "plan.docx"),
        ("evil\x00\x07name.txt", "evilname.txt"),
        (None, "proposal"),
        ("   ", "proposal"),
        ("a" * 400 + ".txt", ("a" * 400 + ".txt")[:255]),
    ],
)
def test_display_name_is_cleaned_and_never_a_path(raw, expected):
    assert display_name(raw) == expected
