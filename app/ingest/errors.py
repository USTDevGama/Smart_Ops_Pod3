"""The error the ingest readers raise."""


class ExtractionError(Exception):
    """The file could not be read. The message is fixed and never contains file text."""
