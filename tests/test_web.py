from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conferir_ponto.persistence import create_user, hydrate_local_cache_from_d1
import conferir_ponto.persistence as persistence_module
from conferir_ponto.storage import LocalReportStorage, storage_from_env
from conferir_ponto.web import REPORTS, app, hash_password, sanitize_download_name
import conferir_ponto.web as web_module


class WebAppTests(unittest.TestCase):
    def setUp(self):
        REPORTS.clear()
        web_module._REPORT_STORAGE = None
        persistence_module._D1_CLIENT = False
        self._temp_dir = TemporaryDirectory()
        self._db_patcher = patch(
            "conferir_ponto.persistence.APP_DB_PATH",
            Path(self._temp_dir.name) / "app.db",
        )
        self._db_patcher.start()

    def tearDown(self):
        self._db_patcher.stop()
        web_module._REPORT_STORAGE = None
        persistence_module._D1_CLIENT = False
        self._temp_dir.cleanup()

    def login_admin(self, client: TestClient, username: str = "admin", password: str = "secret123"):
        return client.post(
            "/api/admin/session",
            json={"username": username, "password": password},
        )

    def login_app(self, client: TestClient, username: str = "operador", password: str = "senha123", role: str = "user"):
        create_user(
            username=username,
            password_hash=hash_password(password),
            role=role,
            display_name=username.title(),
        )
        return client.post(
            "/api/session",
            json={"username": username, "password": password},
        )

    def test_process_endpoint_returns_summary(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "fev2026.pdf"
        client = TestClient(app)
        self.login_app(client)

        with pdf_path.open("rb") as file:
            response = client.post(
                "/api/process",
                files={"file": (pdf_path.name, file, "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["businessDaysProcessed"], 22)
        self.assertEqual(payload["schedule"]["start"], "07:45")
        self.assertEqual(payload["schedule"]["end"], "17:00")
        self.assertIn("diagnostics", payload)
        self.assertIn("meta", payload)
        self.assertIn("processingDurationMs", payload["meta"])
        self.assertIn("paidOvertime", payload["summary"])
        self.assertIn("journeyCode", payload["days"][0])
        self.assertIn("appliedSchedule", payload["days"][0])
        self.assertIn("reportId", payload)

    def test_export_endpoint_returns_pdf(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO.pdf"
        client = TestClient(app)
        self.login_app(client)

        with pdf_path.open("rb") as file:
            process_response = client.post(
                "/api/process",
                files={"file": (pdf_path.name, file, "application/pdf")},
            )

        report_id = process_response.json()["reportId"]
        export_response = client.get(f"/api/export/{report_id}")

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.headers["content-type"], "application/pdf")
        self.assertIn(".pdf", export_response.headers["content-disposition"])
        self.assertEqual(export_response.headers["cache-control"], "no-store")
        self.assertEqual(export_response.headers["x-content-type-options"], "nosniff")
        self.assertTrue(export_response.content.startswith(b"%PDF"))

    def test_process_endpoint_rejects_large_pdf(self):
        client = TestClient(app)
        self.login_app(client)
        oversized_content = b"%PDF-1.4\n" + (b"0" * (10 * 1024 * 1024))

        response = client.post(
            "/api/process",
            files={"file": ("grande.pdf", oversized_content, "application/pdf")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("10 MB", response.json()["detail"])

    def test_export_endpoint_sanitizes_download_filename(self):
        client = TestClient(app)
        self.login_app(client, username="adminuser", password="senha123", role="admin")
        REPORTS["report-safe"] = {
            "filename": 'evil"\r\nX-Test: injected.pdf',
            "pdf": b"%PDF-1.4\nsafe\n",
            "payload": {
                "meta": {
                    "owner": {
                        "username": "adminuser",
                        "role": "admin",
                    }
                }
            },
        }

        response = client.get("/api/export/report-safe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="evil_X-Test_injected_apuracao.pdf"',
        )

    def test_frontend_renders_pdf_content_without_inner_html_injection(self):
        app_js = (PROJECT_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("issuesListEl.innerHTML", app_js)
        self.assertNotIn("daysTableEl.innerHTML", app_js)
        self.assertNotIn("summaryGridEl.innerHTML", app_js)
        self.assertIn("createTextNode", app_js)

    def test_api_docs_are_disabled_by_default(self):
        client = TestClient(app)

        response = client.get("/docs")

        self.assertEqual(response.status_code, 404)

    def test_main_page_redirects_to_login_when_not_authenticated(self):
        client = TestClient(app)

        response = client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_app_login_sets_session_cookie(self):
        client = TestClient(app)

        response = self.login_app(client)

        self.assertEqual(response.status_code, 200)
        self.assertIn("agent_app_session", response.headers.get("set-cookie", ""))

    def test_authenticated_user_can_open_main_page(self):
        client = TestClient(app)
        self.login_app(client)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Apuração de Ponto", response.text)

    def test_app_logout_clears_session_cookie(self):
        client = TestClient(app)
        self.login_app(client)

        response = client.delete("/api/session")

        self.assertEqual(response.status_code, 200)
        self.assertIn("agent_app_session=", response.headers.get("set-cookie", ""))

    def test_authenticated_user_can_change_own_password(self):
        client = TestClient(app)
        self.login_app(client, username="operador", password="senha123")

        response = client.post(
            "/api/session/password",
            json={
                "currentPassword": "senha123",
                "newPassword": "novaSenha123",
                "confirmPassword": "novaSenha123",
            },
        )

        self.assertEqual(response.status_code, 200)
        client.delete("/api/session")
        old_login = client.post("/api/session", json={"username": "operador", "password": "senha123"})
        new_login = client.post("/api/session", json={"username": "operador", "password": "novaSenha123"})
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

    def test_change_password_rejects_incorrect_current_password(self):
        client = TestClient(app)
        self.login_app(client, username="operador", password="senha123")

        response = client.post(
            "/api/session/password",
            json={
                "currentPassword": "senhaErrada",
                "newPassword": "novaSenha123",
                "confirmPassword": "novaSenha123",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("senha atual", response.json()["detail"].lower())

    def test_admin_page_redirects_when_not_authenticated(self):
        client = TestClient(app)

        response = client.get("/admin", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_login_sets_session_cookie(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            response = self.login_admin(client)

        self.assertEqual(response.status_code, 200)
        self.assertIn("agent_admin_session", response.headers.get("set-cookie", ""))

    def test_database_backed_admin_login_sets_session_cookie(self):
        client = TestClient(app)
        create_user(
            username="dbadmin",
            password_hash=hash_password("secret123"),
            role="admin",
            display_name="DB Admin",
        )

        with patch.dict("os.environ", {"ADMIN_PASSWORD": ""}, clear=False):
            response = self.login_admin(client, username="dbadmin", password="secret123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "dbadmin")
        self.assertIn("agent_admin_session", response.headers.get("set-cookie", ""))

    def test_admin_session_status_returns_authenticated_user(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.get("/api/admin/session")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertEqual(response.json()["user"]["username"], "admin")

    def test_settings_requires_admin_authentication(self):
        client = TestClient(app)

        response = client.get("/api/settings")

        self.assertEqual(response.status_code, 401)

    def test_admin_can_create_and_list_users(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            create_response = client.post(
                "/api/admin/users",
                json={
                    "username": "operador",
                    "password": "senha123",
                    "role": "user",
                    "displayName": "Operador",
                    "email": "operador@example.com",
                },
            )
            list_response = client.get("/api/admin/users")

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["username"], "operador")
        self.assertEqual(create_response.json()["role"], "user")
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(list_response.json()["count"], 2)
        self.assertIn("operador", [item["username"] for item in list_response.json()["items"]])

    def test_admin_user_history_lists_create_and_update_actions(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            client.post(
                "/api/admin/users",
                json={
                    "username": "operador",
                    "password": "senha123",
                    "role": "user",
                    "displayName": "Operador",
                },
            )
            client.put(
                "/api/admin/users/operador",
                json={
                    "role": "admin",
                    "displayName": "Operador Lider",
                },
            )
            history_response = client.get("/api/admin/users/history")

        self.assertEqual(history_response.status_code, 200)
        payload = history_response.json()
        self.assertEqual(payload["count"], 2)
        self.assertTrue(all(item["targetUsername"] == "operador" for item in payload["items"]))
        self.assertEqual({item["action"] for item in payload["items"]}, {"create", "update"})

    def test_user_audit_history_recovers_after_d1_missing_table(self):
        class FakeD1Client:
            def __init__(self):
                self.query_calls = 0
                self.ensure_calls = 0

            def query(self, sql, params):
                self.query_calls += 1
                if self.query_calls == 1:
                    raise RuntimeError(
                        'D1 HTTP error 400: {"messages":[],"result":[],"success":false,'
                        '"errors":[{"code":7500,"message":"no such table: user_audit: SQLITE_ERROR"}]}'
                    )
                return [
                    {
                        "changed_at": "2026-04-24T12:00:00",
                        "actor": "admin",
                        "target_username": "operador",
                        "action": "update",
                        "changes_json": '["Perfil alterado para admin"]',
                    }
                ]

            def ensure_schema(self, *, force=False):
                self.ensure_calls += 1

        fake_d1 = FakeD1Client()
        persistence_module._D1_CLIENT = fake_d1

        with patch.dict("os.environ", {"D1_PREFER_READS": "true"}, clear=False):
            items = persistence_module.list_user_audit_entries()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["targetUsername"], "operador")
        self.assertEqual(fake_d1.ensure_calls, 1)
        self.assertEqual(fake_d1.query_calls, 2)

    def test_admin_settings_fall_back_when_d1_current_payload_is_invalid_json(self):
        class FakeD1Client:
            def query(self, sql, params=None):
                normalized = " ".join(str(sql).split()).lower()
                if "from settings_current" in normalized:
                    return [{"payload_json": '{"defaultSchedule":', "updated_at": "2026-04-25T03:00:00"}]
                if "from settings_audit" in normalized:
                    return []
                return []

            def ensure_schema(self, *, force=False):
                return None

        persistence_module._D1_CLIENT = FakeD1Client()
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["defaultSchedule"]["start"], "07:45")
        self.assertIn("0004", payload["journeySchedules"])

    def test_admin_settings_load_even_when_d1_bootstrap_write_fails(self):
        class FakeD1Client:
            def query(self, sql, params=None):
                normalized = " ".join(str(sql).split()).lower()
                if "from settings_current" in normalized:
                    return []
                if "from settings_audit" in normalized:
                    return []
                return []

            def execute(self, sql, params=None):
                raise RuntimeError("D1 write failed")

            def ensure_schema(self, *, force=False):
                return None

        persistence_module._D1_CLIENT = FakeD1Client()
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["defaultSchedule"]["start"], "07:45")
        self.assertIn("0999", payload["journeySchedules"])

    def test_admin_settings_history_skips_invalid_d1_rows(self):
        class FakeD1Client:
            def query(self, sql, params=None):
                normalized = " ".join(str(sql).split()).lower()
                if "from settings_current" in normalized:
                    return []
                if "from settings_audit" in normalized:
                    return [
                        {
                            "changed_at": "2026-04-25T03:00:00",
                            "actor": "admin",
                            "changes_json": '["Jornada alterada"]',
                            "settings_json": '{"defaultSchedule":{"start":"07:45","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"}}',
                        },
                        {
                            "changed_at": "2026-04-24T03:00:00",
                            "actor": "admin",
                            "changes_json": '["registro ruim"]',
                            "settings_json": '{"defaultSchedule":',
                        },
                    ]
                return []

            def ensure_schema(self, *, force=False):
                return None

        persistence_module._D1_CLIENT = FakeD1Client()
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.get("/api/settings/history")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["actor"], "admin")

    def test_admin_can_update_existing_user(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            client.post(
                "/api/admin/users",
                json={
                    "username": "operador",
                    "password": "senha123",
                    "role": "user",
                    "displayName": "Operador",
                },
            )
            update_response = client.put(
                "/api/admin/users/operador",
                json={
                    "role": "admin",
                    "displayName": "Operador Líder",
                    "isActive": False,
                },
            )
            list_response = client.get("/api/admin/users")

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["role"], "admin")
        self.assertFalse(update_response.json()["isActive"])
        updated_user = next(item for item in list_response.json()["items"] if item["username"] == "operador")
        self.assertEqual(updated_user["displayName"], "Operador Líder")
        self.assertFalse(updated_user["isActive"])

    def test_update_user_preserves_password_when_d1_row_lacks_hash(self):
        with TemporaryDirectory() as temp_dir:
            with patch("conferir_ponto.persistence.APP_DB_PATH", Path(temp_dir) / "app.db"), patch(
                "conferir_ponto.persistence.mirror_execute"
            ), patch.dict("os.environ", {"D1_PREFER_READS": "true"}, clear=False):
                create_user(
                    username="operador",
                    password_hash=hash_password("senha123"),
                    role="user",
                    display_name="Operador",
                )
                persistence_module._D1_CLIENT = SimpleNamespace()
                remote_row = {
                    "id": "remote-operador",
                    "username": "operador",
                    "email": "operador@empresa.com",
                    "display_name": "Operador Remoto",
                    "password_hash": None,
                    "role": "user",
                    "is_active": 1,
                    "created_at": "2026-04-24T00:00:00",
                    "updated_at": "2026-04-24T00:00:00",
                }
                with patch("conferir_ponto.persistence.mirror_fetch_one", return_value=remote_row):
                    updated = persistence_module.update_user(
                        "operador",
                        display_name="Operador Atualizado",
                        email="operador@empresa.com",
                    )

                self.assertEqual(updated["displayName"], "Operador Atualizado")
                self.assertTrue(web_module.verify_password("senha123", updated["passwordHash"]))

    def test_load_user_backfills_d1_when_remote_record_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            with patch("conferir_ponto.persistence.APP_DB_PATH", Path(temp_dir) / "app.db"), patch(
                "conferir_ponto.persistence.mirror_execute"
            ), patch.dict("os.environ", {"D1_PREFER_READS": "true"}, clear=False):
                create_user(
                    username="operador",
                    password_hash=hash_password("senha123"),
                    role="user",
                    display_name="Operador",
                )
                persistence_module._D1_CLIENT = SimpleNamespace()
                with patch("conferir_ponto.persistence.mirror_fetch_one", return_value=None):
                    user = persistence_module.load_user_by_username("operador")

                self.assertEqual(user["username"], "operador")

    def test_list_users_keeps_local_user_visible_when_d1_is_missing_it(self):
        with TemporaryDirectory() as temp_dir:
            with patch("conferir_ponto.persistence.APP_DB_PATH", Path(temp_dir) / "app.db"), patch(
                "conferir_ponto.persistence.mirror_execute"
            ), patch.dict("os.environ", {"D1_PREFER_READS": "true"}, clear=False):
                create_user(
                    username="operador",
                    password_hash=hash_password("senha123"),
                    role="user",
                    display_name="Operador",
                )
                persistence_module._D1_CLIENT = SimpleNamespace()
                with patch("conferir_ponto.persistence.mirror_fetch_all", return_value=[]):
                    items = persistence_module.list_users()

                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["username"], "operador")

    def test_hydrate_local_cache_from_d1_populates_users_from_remote_primary(self):
        class FakeD1Client:
            def query(self, sql, params=None):
                normalized = " ".join(str(sql).split()).lower()
                if "from settings_current" in normalized:
                    return []
                if "from settings_audit" in normalized:
                    return []
                if "from reports" in normalized:
                    return []
                if "from user_audit" in normalized:
                    return []
                if "from users" in normalized:
                    return [
                        {
                            "id": "uuid-user-1",
                            "username": "operador",
                            "email": "operador@example.com",
                            "display_name": "Operador",
                            "password_hash": "hash-1",
                            "role": "user",
                            "is_active": 1,
                            "created_at": "2026-04-25T09:00:00",
                            "updated_at": "2026-04-25T09:00:00",
                        },
                        {
                            "id": "uuid-user-2",
                            "username": "admin2",
                            "email": "admin2@example.com",
                            "display_name": "Admin Dois",
                            "password_hash": "hash-2",
                            "role": "admin",
                            "is_active": 1,
                            "created_at": "2026-04-25T09:05:00",
                            "updated_at": "2026-04-25T09:05:00",
                        },
                    ]
                return []

            def execute(self, sql, params=None):
                return None

            def ensure_schema(self, *, force=False):
                return None

        persistence_module._D1_CLIENT = FakeD1Client()

        summary = hydrate_local_cache_from_d1()
        items = persistence_module.list_users()

        self.assertEqual(summary["users"], 2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], "uuid-user-1")
        self.assertEqual(items[1]["id"], "uuid-user-2")

    def test_admin_can_inspect_persistence_status(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.get("/api/admin/persistence")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["backend"], "sqlite")
        self.assertEqual(response.json()["storageBackend"], "local")
        self.assertFalse(response.json()["enabled"])

    def test_admin_can_run_storage_diagnostics(self):
        class FakeStorage:
            backend_name = "r2"

            def probe(self):
                return {
                    "backend": "r2",
                    "ok": True,
                    "bucket": "rendflare",
                    "key": "_storage_probe/test.txt",
                    "location": "r2://rendflare/_storage_probe/test.txt",
                    "writeOk": True,
                    "readOk": True,
                    "deleteOk": True,
                }

        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False), patch(
            "conferir_ponto.web.report_storage",
            return_value=FakeStorage(),
        ):
            self.login_admin(client)
            response = client.post("/api/admin/storage/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["storage"]["ok"])
        self.assertEqual(payload["status"]["storageBackend"], "r2")
        self.assertEqual(payload["status"]["storageProbe"]["bucket"], "rendflare")

    def test_sync_d1_requires_configuration(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False):
            self.login_admin(client)
            response = client.post("/api/admin/persistence/sync-d1")

        self.assertEqual(response.status_code, 400)
        self.assertIn("D1", response.json()["detail"])

    def test_sync_d1_hydrates_local_cache_from_remote(self):
        client = TestClient(app)

        with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False), patch(
            "conferir_ponto.web.d1_status",
            return_value={
                "enabled": True,
                "backend": "sqlite+d1",
                "preferReads": True,
                "databaseId": "db-id",
                "accountId": "account-id",
            },
        ), patch(
            "conferir_ponto.web.hydrate_local_cache_from_d1",
            return_value={
                "settingsCurrent": 1,
                "settingsAudit": 2,
                "reports": 3,
                "users": 4,
                "userAudit": 5,
            },
        ) as mocked_hydrate:
            self.login_admin(client)
            response = client.post("/api/admin/persistence/sync-d1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["synced"])
        self.assertEqual(response.json()["summary"]["users"], 4)
        mocked_hydrate.assert_called_once()

    def test_healthcheck_returns_security_headers(self):
        client = TestClient(app)

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "1.16.3")
        self.assertEqual(response.json()["storageBackend"], "local")
        self.assertEqual(response.json()["persistenceBackend"], "sqlite")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_healthcheck_reports_d1_mirror_when_available(self):
        client = TestClient(app)
        persistence_module._D1_CLIENT = SimpleNamespace()

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["persistenceBackend"], "sqlite+d1")
        self.assertTrue(response.json()["persistenceBackend"].startswith("sqlite"))

    def test_load_current_settings_prefers_d1_when_enabled(self):
        persistence_module._D1_CLIENT = SimpleNamespace()
        with patch("conferir_ponto.persistence.mirror_fetch_one", return_value={"payload_json": '{"defaultSchedule":{"start":"09:00","lunchStart":"12:00","lunchEnd":"13:00","end":"18:00"}}'}), patch.dict(
            "os.environ",
            {"D1_PREFER_READS": "true"},
            clear=False,
        ):
            payload = persistence_module.load_current_settings_payload()

        self.assertEqual(payload["defaultSchedule"]["start"], "09:00")

    def test_get_settings_returns_persisted_configuration(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "apuracao.json"
            settings_path.write_text(
                '{"defaultSchedule":{"start":"08:00","lunchStart":"12:00","lunchEnd":"13:00","end":"17:30"},"workingWeekdays":[0,1,2,3,4],"paidHours":{"weekends":true,"holidays":true,"statusCodes":["CO","FE","RE"]},"journeySchedules":{"0004":{"start":"08:00","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"},"0048":{"start":"07:45","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"},"0999":{"start":"08:00","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"}},"journeyRules":{"0004":{"countOvertimeBeforeStart":false,"lateToleranceMinutes":7}}}',
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False), patch("conferir_ponto.settings.SETTINGS_PATH", settings_path):
                self.login_admin(client)
                response = client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["defaultSchedule"]["start"], "08:00")
        self.assertEqual(payload["journeySchedules"]["0048"]["start"], "07:45")
        self.assertEqual(payload["journeyRules"]["0004"]["lateToleranceMinutes"], 7)

    def test_put_settings_persists_configuration(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "apuracao.json"
            history_path = Path(temp_dir) / "apuracao-history.jsonl"
            with patch.dict("os.environ", {"ADMIN_PASSWORD": "secret123"}, clear=False), patch("conferir_ponto.settings.SETTINGS_PATH", settings_path), patch("conferir_ponto.settings.SETTINGS_HISTORY_PATH", history_path):
                self.login_admin(client)
                response = client.put(
                    "/api/settings",
                    json={
                        "defaultSchedule": {
                            "start": "08:00",
                            "lunchStart": "12:00",
                            "lunchEnd": "13:00",
                            "end": "17:30",
                        },
                        "workingWeekdays": [0, 1, 2, 3, 4],
                        "paidHours": {
                            "weekends": True,
                            "holidays": True,
                            "statusCodes": ["CO", "FE", "RE"],
                        },
                        "journeySchedules": {
                            "0004": {
                                "start": "08:00",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                            "0048": {
                                "start": "07:45",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                            "0999": {
                                "start": "08:00",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                        },
                        "journeyRules": {
                            "0004": {
                                "countOvertimeBeforeStart": False,
                                "lateToleranceMinutes": 9,
                            }
                        },
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(settings_path.exists())
                persisted = settings_path.read_text(encoding="utf-8")
                history = history_path.read_text(encoding="utf-8")

        self.assertIn('"start": "08:00"', persisted)
        self.assertIn('"0048"', persisted)
        self.assertIn('"lateToleranceMinutes": 9', persisted)
        self.assertIn('"actor": "admin"', history)
        self.assertIn("Jornada padrão", history)

    def test_settings_history_returns_latest_audit_entries(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "apuracao.json"
            history_path = Path(temp_dir) / "apuracao-history.jsonl"
            settings_path.write_text(
                '{"defaultSchedule":{"start":"07:45","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"},"workingWeekdays":[0,1,2,3,4],"paidHours":{"weekends":true,"holidays":true,"statusCodes":["CO","FE","RE"]},"journeySchedules":{"0004":{"start":"08:00","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"},"0048":{"start":"07:45","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"},"0999":{"start":"08:00","lunchStart":"12:00","lunchEnd":"13:00","end":"17:00"}},"journeyRules":{"0004":{"countOvertimeBeforeStart":false,"lateToleranceMinutes":5}}}',
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"ADMIN_USERNAME": "diegoluks", "ADMIN_PASSWORD": "secret123"}, clear=False), patch("conferir_ponto.settings.SETTINGS_PATH", settings_path), patch("conferir_ponto.settings.SETTINGS_HISTORY_PATH", history_path):
                self.login_admin(client, username="diegoluks")
                save_response = client.put(
                    "/api/settings",
                    json={
                        "defaultSchedule": {
                            "start": "08:00",
                            "lunchStart": "12:00",
                            "lunchEnd": "13:00",
                            "end": "17:30",
                        },
                        "workingWeekdays": [0, 1, 2, 3, 4],
                        "paidHours": {
                            "weekends": True,
                            "holidays": True,
                            "statusCodes": ["CO", "FE", "RE"],
                        },
                        "journeySchedules": {
                            "0004": {
                                "start": "08:00",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                            "0048": {
                                "start": "07:45",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                            "0999": {
                                "start": "08:00",
                                "lunchStart": "12:00",
                                "lunchEnd": "13:00",
                                "end": "17:00",
                            },
                        },
                        "journeyRules": {
                            "0004": {
                                "countOvertimeBeforeStart": False,
                                "lateToleranceMinutes": 9,
                            }
                        },
                    },
                )
                response = client.get("/api/settings/history")

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["actor"], "diegoluks")
        self.assertIn("Jornada padrão", payload["items"][0]["changes"][0])

    def test_recent_reports_endpoint_returns_latest_items(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        with TemporaryDirectory() as temp_dir, patch("conferir_ponto.web.REPORTS_DIR", Path(temp_dir)):
            REPORTS["first"] = {
                "filename": "a.pdf",
                "pdf": b"%PDF-1.4\n",
                "recent": {
                    "reportId": "first",
                    "filename": "a.pdf",
                    "employeeName": "Primeiro",
                    "periodStart": "2026-04-01",
                    "periodEnd": "2026-04-30",
                    "processedAt": "2026-04-22T10:00:00",
                    "createdAt": "2026-04-22T10:00:00",
                    "processingDurationMs": 120,
                    "ownerUsername": "viewer",
                    "summary": {"businessDaysProcessed": 20, "inconsistencyCount": 1, "balance": "00:10", "paidOvertime": "00:00"},
                    "diagnostics": {"ignoredDays": 2},
                },
                "payload": {"meta": {"owner": {"username": "viewer", "role": "user"}}},
            }
            REPORTS["second"] = {
                "filename": "b.pdf",
                "pdf": b"%PDF-1.4\n",
                "recent": {
                    "reportId": "second",
                    "filename": "b.pdf",
                    "employeeName": "Segundo",
                    "periodStart": "2026-05-01",
                    "periodEnd": "2026-05-31",
                    "processedAt": "2026-05-22T10:00:00",
                    "createdAt": "2026-05-22T10:00:00",
                    "processingDurationMs": 95,
                    "ownerUsername": "viewer",
                    "summary": {"businessDaysProcessed": 21, "inconsistencyCount": 0, "balance": "01:00", "paidOvertime": "02:00"},
                    "diagnostics": {"ignoredDays": 0},
                },
                "payload": {"meta": {"owner": {"username": "viewer", "role": "user"}}},
            }

            response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["items"][0]["reportId"], "second")
        self.assertEqual(payload["items"][1]["reportId"], "first")

    def test_recent_reports_endpoint_reads_persisted_items(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            reports_dir.joinpath("reports", "older").mkdir(parents=True)
            reports_dir.joinpath("reports", "older", "metadata.json").write_text(
                '{"reportId":"older","filename":"older.pdf","recent":{"reportId":"older","filename":"older.pdf","employeeName":"Mais antigo","createdAt":"2026-04-22T10:00:00","ownerUsername":"viewer","summary":{"balance":"00:10","inconsistencyCount":1,"paidOvertime":"00:00","businessDaysProcessed":20},"diagnostics":{}}}',
                encoding="utf-8",
            )
            reports_dir.joinpath("reports", "newer").mkdir(parents=True)
            reports_dir.joinpath("reports", "newer", "metadata.json").write_text(
                '{"reportId":"newer","filename":"newer.pdf","recent":{"reportId":"newer","filename":"newer.pdf","employeeName":"Mais novo","createdAt":"2026-04-23T10:00:00","ownerUsername":"viewer","summary":{"balance":"01:00","inconsistencyCount":0,"paidOvertime":"02:00","businessDaysProcessed":21},"diagnostics":{}}}',
                encoding="utf-8",
            )
            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"][0]["reportId"], "newer")
        self.assertEqual(payload["items"][1]["reportId"], "older")

    def test_recent_reports_endpoint_filters_items_by_authenticated_user(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            reports_dir.joinpath("reports", "viewer-report").mkdir(parents=True)
            reports_dir.joinpath("reports", "viewer-report", "metadata.json").write_text(
                '{"reportId":"viewer-report","filename":"viewer.pdf","recent":{"reportId":"viewer-report","ownerUsername":"viewer","createdAt":"2026-04-23T10:00:00"}}',
                encoding="utf-8",
            )
            reports_dir.joinpath("reports", "other-report").mkdir(parents=True)
            reports_dir.joinpath("reports", "other-report", "metadata.json").write_text(
                '{"reportId":"other-report","filename":"other.pdf","recent":{"reportId":"other-report","ownerUsername":"other","createdAt":"2026-04-24T10:00:00"}}',
                encoding="utf-8",
            )

            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["items"][0]["reportId"], "viewer-report")

    def test_export_endpoint_falls_back_to_persisted_report(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_id = "persisted-report"
            reports_dir.joinpath("reports", report_id).mkdir(parents=True)
            reports_dir.joinpath("reports", report_id, "metadata.json").write_text(
                '{"reportId":"persisted-report","filename":"persisted.pdf","recent":{"reportId":"persisted-report","filename":"persisted.pdf","createdAt":"2026-04-23T10:00:00","ownerUsername":"viewer","summary":{"balance":"00:00","inconsistencyCount":0,"paidOvertime":"00:00","businessDaysProcessed":1},"diagnostics":{}},"payload":{"reportId":"persisted-report","employeeName":"Persistido","meta":{"owner":{"username":"viewer","role":"user"}}}}',
                encoding="utf-8",
            )
            reports_dir.joinpath("reports", report_id, "export.pdf").write_bytes(b"%PDF-1.4\npersisted\n")

            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get(f"/api/export/{report_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("persisted_apuracao.pdf", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_report_details_endpoint_returns_persisted_payload(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_id = "persisted-report"
            reports_dir.joinpath("reports", report_id).mkdir(parents=True)
            reports_dir.joinpath("reports", report_id, "metadata.json").write_text(
                '{"reportId":"persisted-report","filename":"persisted.pdf","recent":{"reportId":"persisted-report","ownerUsername":"viewer"},"payload":{"reportId":"persisted-report","employeeName":"Persistido","summary":{"businessDaysProcessed":3},"meta":{"owner":{"username":"viewer","role":"user"}}}}',
                encoding="utf-8",
            )
            reports_dir.joinpath("reports", report_id, "export.pdf").write_bytes(b"%PDF-1.4\npersisted\n")

            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get(f"/api/reports/{report_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reportId"], "persisted-report")
        self.assertEqual(payload["employeeName"], "Persistido")
        self.assertEqual(payload["summary"]["businessDaysProcessed"], 3)

    def test_report_details_forbids_access_to_other_user_report(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        REPORTS["foreign-report"] = {
            "filename": "foreign.pdf",
            "pdf": b"%PDF-1.4\ncached\n",
            "recent": {"reportId": "foreign-report", "ownerUsername": "other"},
            "payload": {
                "reportId": "foreign-report",
                "employeeName": "Outro",
                "meta": {"owner": {"username": "other", "role": "user"}},
            },
        }

        response = client.get("/api/reports/foreign-report")

        self.assertEqual(response.status_code, 403)

    def test_report_cache_discards_oldest_entry_when_limit_is_reached(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        for index in range(32):
            REPORTS[f"existing-{index}"] = {
                "filename": f"report-{index}.pdf",
                "pdf": b"%PDF-1.4\ncached\n",
                "recent": {"reportId": f"existing-{index}"},
                "payload": {"meta": {"owner": {"username": "viewer", "role": "user"}}},
            }

        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }

        with patch("conferir_ponto.web.parse_timecard_bytes", return_value=object()), patch(
            "conferir_ponto.web.build_summary_payload", return_value=fake_payload
        ), patch("conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\nnew\n"):
            response = client.post(
                "/api/process",
                files={"file": ("novo.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(REPORTS), 32)
        self.assertNotIn("existing-0", REPORTS)

    def test_process_endpoint_persists_report_files(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }
        with TemporaryDirectory() as temp_dir, patch("conferir_ponto.web.REPORTS_DIR", Path(temp_dir)), patch(
            "conferir_ponto.web.parse_timecard_bytes", return_value=object()
        ), patch("conferir_ponto.web.build_summary_payload", return_value=fake_payload), patch(
            "conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\npersisted\n"
        ):
            response = client.post(
                "/api/process",
                files={"file": ("persistir.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )

            self.assertEqual(response.status_code, 200)
            response_payload = response.json()
            report_id = response_payload["reportId"]
            persisted_metadata = Path(temp_dir, "reports", report_id, "metadata.json")
            self.assertTrue(persisted_metadata.exists())
            self.assertTrue(Path(temp_dir, "reports", report_id, "export.pdf").exists())
            self.assertTrue(Path(temp_dir, "reports", report_id, "source.pdf").exists())
            self.assertIn('"payload"', persisted_metadata.read_text(encoding="utf-8"))
            self.assertIn(response_payload["reportId"], persisted_metadata.read_text(encoding="utf-8"))

    def test_process_endpoint_attributes_report_to_authenticated_user(self):
        client = TestClient(app)
        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }

        create_user(
            username="analista",
            password_hash=hash_password("senha123"),
            role="admin",
            display_name="Analista",
        )
        with patch(
            "conferir_ponto.web.parse_timecard_bytes", return_value=object()
        ), patch("conferir_ponto.web.build_summary_payload", return_value=fake_payload), patch(
            "conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\nowner\n"
        ):
            client.post("/api/session", json={"username": "analista", "password": "senha123"})
            response = client.post(
                "/api/process",
                files={"file": ("owner.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )
            recent_response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meta"]["owner"]["username"], "analista")
        self.assertEqual(recent_response.status_code, 200)
        self.assertEqual(recent_response.json()["items"][0]["ownerUsername"], "analista")

    def test_process_endpoint_still_returns_summary_when_persistence_fails(self):
        client = TestClient(app)
        self.login_app(client, username="viewer", password="senha123")
        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }

        with patch("conferir_ponto.web.parse_timecard_bytes", return_value=object()), patch(
            "conferir_ponto.web.build_summary_payload", return_value=fake_payload
        ), patch("conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\nowner\n"), patch(
            "conferir_ponto.web.persist_report", side_effect=RuntimeError("storage down")
        ):
            response = client.post(
                "/api/process",
                files={"file": ("owner.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["employeeName"], "Teste")
        self.assertIn("persistenceWarning", payload["meta"])


class WebHelpersTests(unittest.TestCase):
    def test_sanitize_download_name_removes_unsafe_characters(self):
        self.assertEqual(
            sanitize_download_name(' ../evil"\r\nname?.pdf '),
            "evil_name",
        )

    def test_storage_from_env_falls_back_to_local_when_r2_is_incomplete(self):
        with patch.dict("os.environ", {}, clear=False):
            storage = storage_from_env(Path("D:/tmp/reports"))

        self.assertIsInstance(storage, LocalReportStorage)
        self.assertEqual(storage.backend_name, "local")

    def test_storage_from_env_uses_r2_when_all_variables_exist(self):
        with patch.dict(
            "os.environ",
            {
                "R2_ENDPOINT_URL": "https://example-account.r2.cloudflarestorage.com",
                "R2_BUCKET_NAME": "agent-ia-ponto",
                "R2_ACCESS_KEY_ID": "abc",
                "R2_SECRET_ACCESS_KEY": "def",
                "R2_REGION": "auto",
            },
            clear=False,
        ), patch("conferir_ponto.storage.R2ReportStorage") as mocked_storage:
            mocked_storage.return_value.backend_name = "r2"
            storage = storage_from_env(Path("D:/tmp/reports"))

        mocked_storage.assert_called_once()
        self.assertEqual(storage.backend_name, "r2")

    def test_update_user_uses_upsert_for_d1_mirror(self):
        class FakeD1Client:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=None):
                self.calls.append((sql, params))

            def ensure_schema(self, *, force=False):
                return None

        with TemporaryDirectory() as temp_dir:
            with patch("conferir_ponto.persistence.APP_DB_PATH", Path(temp_dir) / "app.db"):
                create_user(
                    username="operador",
                    password_hash=hash_password("senha123"),
                    role="user",
                    display_name="Operador",
                )
                fake_d1 = FakeD1Client()
                persistence_module._D1_CLIENT = fake_d1

                persistence_module.update_user(
                    "operador",
                    role="admin",
                    display_name="Operador Lider",
                )

        sql = fake_d1.calls[-1][0]
        self.assertIn("ON CONFLICT(username) DO UPDATE", sql)


if __name__ == "__main__":
    unittest.main()
