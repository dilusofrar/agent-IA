from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from time import time
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class StoredObject:
    key: str
    location: str


class ReportStorage(Protocol):
    def write_bytes(self, key: str, content: bytes) -> StoredObject: ...

    def read_bytes(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def probe(self) -> dict[str, object]: ...

    @property
    def backend_name(self) -> str: ...


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

    def probe(self) -> dict[str, object]:
        probe_key = f"_storage_probe/{int(time())}-{uuid4().hex}.txt"
        payload = b"local-storage-probe"
        try:
            stored = self.write_bytes(probe_key, payload)
            read_back = self.read_bytes(probe_key)
            delete_ok = False
            try:
                self.delete(probe_key)
                delete_ok = not self.exists(probe_key)
            finally:
                self.delete(probe_key)
            return {
                "backend": self.backend_name,
                "ok": read_back == payload and delete_ok,
                "bucket": None,
                "key": probe_key,
                "location": stored.location,
                "writeOk": True,
                "readOk": read_back == payload,
                "deleteOk": delete_ok,
            }
        except Exception as exc:
            return {
                "backend": self.backend_name,
                "ok": False,
                "bucket": None,
                "key": probe_key,
                "writeOk": False,
                "readOk": False,
                "deleteOk": False,
                "error": str(exc),
            }

    def _path_for(self, key: str) -> Path:
        parts = [part for part in key.replace("\\", "/").split("/") if part]
        return self.root_dir.joinpath(*parts)

    @property
    def backend_name(self) -> str:
        return "local"


class R2ReportStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str = "auto",
    ) -> None:
        import boto3
        from botocore.exceptions import ClientError

        self.bucket_name = bucket_name
        self._client_error = ClientError
        self.client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name or "auto",
        )

    def write_bytes(self, key: str, content: bytes) -> StoredObject:
        self.client.put_object(Bucket=self.bucket_name, Key=key, Body=content)
        return StoredObject(key=key, location=f"r2://{self.bucket_name}/{key}")

    def read_bytes(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=key)
        except self._client_error as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except self._client_error as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return False
            raise

    def probe(self) -> dict[str, object]:
        probe_key = f"_storage_probe/{int(time())}-{uuid4().hex}.txt"
        payload = f"r2-storage-probe:{probe_key}".encode("utf-8")
        delete_ok = False
        try:
            stored = self.write_bytes(probe_key, payload)
            read_back = self.read_bytes(probe_key)
            try:
                self.delete(probe_key)
                delete_ok = not self.exists(probe_key)
            finally:
                if not delete_ok:
                    try:
                        self.delete(probe_key)
                    except Exception:
                        pass
            return {
                "backend": self.backend_name,
                "ok": read_back == payload and delete_ok,
                "bucket": self.bucket_name,
                "key": probe_key,
                "location": stored.location,
                "writeOk": True,
                "readOk": read_back == payload,
                "deleteOk": delete_ok,
            }
        except Exception as exc:
            return {
                "backend": self.backend_name,
                "ok": False,
                "bucket": self.bucket_name,
                "key": probe_key,
                "writeOk": False,
                "readOk": False,
                "deleteOk": False,
                "error": str(exc),
            }

    @property
    def backend_name(self) -> str:
        return "r2"


def storage_from_env(root_dir: Path) -> ReportStorage:
    endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
    bucket_name = os.getenv("R2_BUCKET_NAME", "").strip()
    access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    region_name = os.getenv("R2_REGION", "auto").strip() or "auto"

    if endpoint_url and bucket_name and access_key_id and secret_access_key:
        return R2ReportStorage(
            endpoint_url=endpoint_url,
            bucket_name=bucket_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
        )
    return LocalReportStorage(root_dir)


def build_report_object_key(report_id: str, filename: str) -> str:
    return f"reports/{report_id}/{filename}"
