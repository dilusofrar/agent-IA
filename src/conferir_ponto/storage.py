from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    location: str


class ReportStorage(Protocol):
    def write_bytes(self, key: str, content: bytes) -> StoredObject: ...

    def read_bytes(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class LocalReportStorage:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def write_bytes(self, key: str, content: bytes) -> StoredObject:
        target_path = self._path_for(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return StoredObject(key=key, location=str(target_path))

    def read_bytes(self, key: str) -> bytes | None:
        target_path = self._path_for(key)
        if not target_path.exists():
            return None
        return target_path.read_bytes()

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def _path_for(self, key: str) -> Path:
        parts = [part for part in key.replace("\\", "/").split("/") if part]
        return self.root_dir.joinpath(*parts)


def build_report_object_key(report_id: str, filename: str) -> str:
    return f"reports/{report_id}/{filename}"
