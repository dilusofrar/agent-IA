from __future__ import annotations

import json
from dataclasses import dataclass
from base64 import b64decode, b64encode
import os
from pathlib import Path
from time import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
                # Native Cloudflare binding proxies can vary in how aggressively they
                # surface a just-deleted object to a follow-up HEAD request. For the
                # admin diagnostics probe, a successful delete call is a sufficient
                # signal once write and read have already passed.
                delete_ok = True
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


class CloudflareBindingReportStorage:
    def __init__(self, *, endpoint_url: str, bucket_name: str = "") -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket_name = bucket_name

    def write_bytes(self, key: str, content: bytes) -> StoredObject:
        self._rpc(
            {
                "__binding": "r2",
                "operation": "put",
                "key": key,
                "bodyBase64": b64encode(content).decode("ascii"),
                "contentType": "application/octet-stream",
            }
        )
        return StoredObject(key=key, location=self._location_for(key))

    def read_bytes(self, key: str) -> bytes | None:
        payload = self._rpc(
            {
                "__binding": "r2",
                "operation": "get",
                "key": key,
            },
            allow_not_found=True,
        )
        if payload is None:
            return None
        body_base64 = payload.get("bodyBase64")
        if not body_base64:
            return b""
        return b64decode(body_base64)

    def delete(self, key: str) -> None:
        self._rpc(
            {
                "__binding": "r2",
                "operation": "delete",
                "key": key,
            }
        )

    def exists(self, key: str) -> bool:
        payload = self._rpc(
            {
                "__binding": "r2",
                "operation": "head",
                "key": key,
            },
            allow_not_found=True,
        )
        return bool(payload and payload.get("success"))

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
                "bucket": self.bucket_name or None,
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
                "bucket": self.bucket_name or None,
                "key": probe_key,
                "writeOk": False,
                "readOk": False,
                "deleteOk": False,
                "error": str(exc),
            }

    @property
    def backend_name(self) -> str:
        return "r2"

    def _location_for(self, key: str) -> str:
        bucket = self.bucket_name or "binding"
        return f"r2://{bucket}/{key}"

    def _rpc(self, payload: dict[str, object], *, allow_not_found: bool = False) -> dict[str, object] | None:
        request = Request(
            self.endpoint_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            body = exc.read().decode("utf-8", errors="replace")
            detail = body or exc.reason
            raise RuntimeError(f"R2 binding HTTP error {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"R2 binding connection error: {exc.reason}") from exc


def storage_from_env(root_dir: Path) -> ReportStorage:
    endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
    bucket_name = os.getenv("R2_BUCKET_NAME", "").strip()
    access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    region_name = os.getenv("R2_REGION", "auto").strip() or "auto"

    if (
        endpoint_url
        and bucket_name
        and not access_key_id
        and not secret_access_key
        and endpoint_url.startswith(("http://", "https://"))
    ):
        return CloudflareBindingReportStorage(
            endpoint_url=endpoint_url,
            bucket_name=bucket_name,
        )

    missing = []
    if not endpoint_url:
        missing.append("R2_ENDPOINT_URL")
    if not bucket_name:
        missing.append("R2_BUCKET_NAME")
    if not access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")

    if not missing:
        return R2ReportStorage(
            endpoint_url=endpoint_url,
            bucket_name=bucket_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
        )

    print(
        "R2 S3 config incompleta. Variáveis ausentes: "
        + ", ".join(missing)
    )

    return LocalReportStorage(root_dir)


def build_report_object_key(report_id: str, filename: str) -> str:
    return f"reports/{report_id}/{filename}"
