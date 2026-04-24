from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parents[2]
D1_SCHEMA_PATH = BASE_DIR / "docs" / "d1-schema.sql"


def _serialize_param(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    return value


class D1ApiClient:
    def __init__(
        self,
        *,
        account_id: str,
        database_id: str,
        api_token: str,
        base_url: str = "https://api.cloudflare.com/client/v4",
    ) -> None:
        self.account_id = account_id
        self.database_id = database_id
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self._schema_ensured = False

    @property
    def enabled(self) -> bool:
        return bool(self.account_id and self.database_id and self.api_token)

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = [_serialize_param(value) for value in params]
        response = self._post("/query", payload)
        return self._extract_results(response)

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> None:
        payload: dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = [_serialize_param(value) for value in params]
        self._post("/query", payload)

    def execute_script(self, sql_script: str) -> None:
        statements = [
            statement.strip()
            for statement in sql_script.split(";")
            if statement.strip()
        ]
        if not statements:
            return
        self._post(
            "/query",
            {"batch": [{"sql": statement} for statement in statements]},
        )

    def ensure_schema(self, *, force: bool = False) -> None:
        if (self._schema_ensured and not force) or not D1_SCHEMA_PATH.exists():
            return
        self.execute_script(D1_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._schema_ensured = True

    def _post(self, suffix: str, body: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.base_url}/accounts/{self.account_id}/d1/database/{self.database_id}"
            f"{suffix}"
        )
        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"D1 HTTP error {exc.code}: {message}") from exc
        except URLError as exc:
            raise RuntimeError(f"D1 connection error: {exc.reason}") from exc
        if not payload.get("success", False):
            errors = payload.get("errors") or []
            error_message = "; ".join(
                str(item.get("message", "unknown error")) for item in errors
            ) or "D1 operation failed."
            raise RuntimeError(error_message)
        return payload

    def _extract_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = payload.get("result")
        if isinstance(result, list):
            first = result[0] if result else {}
            if isinstance(first, dict):
                rows = first.get("results")
                if isinstance(rows, list):
                    return rows
        if isinstance(result, dict):
            rows = result.get("results")
            if isinstance(rows, list):
                return rows
        return []


def d1_from_env() -> D1ApiClient | None:
    account_id = (
        os.getenv("D1_ACCOUNT_ID", "").strip()
        or os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    )
    database_id = os.getenv("D1_DATABASE_ID", "").strip()
    api_token = (
        os.getenv("D1_API_TOKEN", "").strip()
        or os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    )
    base_url = os.getenv("D1_API_BASE_URL", "https://api.cloudflare.com/client/v4").strip()
    if not account_id or not database_id or not api_token:
        return None
    return D1ApiClient(
        account_id=account_id,
        database_id=database_id,
        api_token=api_token,
        base_url=base_url or "https://api.cloudflare.com/client/v4",
    )
