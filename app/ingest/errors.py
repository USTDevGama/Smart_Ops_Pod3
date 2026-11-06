"""The errors the ingest code raises."""


class ExtractionError(Exception):
    """The file could not be read. The message is fixed and never contains file text."""


class TransientIngestError(Exception):
    """Not the file's fault (storage or database hiccup): the job should be tried again."""
