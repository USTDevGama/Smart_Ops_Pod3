"""Where uploaded files are kept. Local folder for now; cloud blob storage can replace this class.

A `blob_uri` stored on a proposal is a key relative to the root, such as
`proposals/<id>/original.pdf`, so the same row still works if the root moves. Keys are built
here from UUIDs, never from file names.
"""

from pathlib import Path


class BlobStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def path(self, key: str) -> Path:
        return self._path(key)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
        # Remove the now-empty per-proposal folder too; ignore it if something else is in there.
        try:
            self._path(key).parent.rmdir()
        except OSError:
            pass

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("blob key escapes the storage root")
        return path
