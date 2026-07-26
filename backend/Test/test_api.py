import importlib
import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_path = Path(tempfile.gettempdir()) / "ai-video-api-tests.db"
        os.environ["DATABASE_PATH"] = str(cls.database_path)
        try:
            cls.database_path.unlink()
        except FileNotFoundError:
            pass

        import app.main

        cls.main = importlib.reload(app.main)

    @classmethod
    def tearDownClass(cls):
        for path in (cls.database_path, Path(f"{cls.database_path}-journal")):
            for _ in range(20):
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.25)

    def request(self, method, path, body=None, token=None, form=False):
        if form:
            payload = urlencode(body or {}).encode("utf-8")
        else:
            payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": BytesIO(payload),
        }
        if token:
            environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"

        response_info = {}
        response = b"".join(
            self.main.app(environ, lambda status, headers: response_info.update(status=status, headers=headers))
        )
        return response_info["status"], json.loads(response)

    def authenticate(self):
        email = "user@example.com"
        status, _ = self.request(
            "POST",
            "/api/auth/register",
            {"email": email, "username": "test-user", "password": "password123"},
        )
        self.assertTrue(status.startswith("201"))
        status, data = self.request(
            "POST", "/api/auth/login", {"username": email, "password": "password123"}, form=True
        )
        self.assertTrue(status.startswith("200"))
        return data["access_token"]

    def test_registration_rejects_short_password(self):
        status, data = self.request(
            "POST",
            "/api/auth/register",
            {"email": "short@example.com", "username": "short-user", "password": "short"},
        )
        self.assertTrue(status.startswith("400"))
        self.assertEqual(data["detail"], "Password must be at least 8 characters")

    def test_api_rejects_non_object_json_and_handles_preflight(self):
        status, data = self.request("POST", "/api/auth/register", ["not", "an", "object"])
        self.assertTrue(status.startswith("400"))
        self.assertEqual(data["detail"], "JSON body must be an object")

        response_info = {}
        response = b"".join(
            self.main.app(
                {"REQUEST_METHOD": "OPTIONS", "PATH_INFO": "/api/auth/login"},
                lambda status, headers: response_info.update(status=status, headers=headers),
            )
        )
        self.assertEqual(response_info["status"], "204 No Content")
        self.assertEqual(response, b"")
        self.assertIn(("Content-Length", "0"), response_info["headers"])

    def test_generation_requires_a_valid_prompt_and_is_private(self):
        token = self.authenticate()
        status, data = self.request(
            "POST", "/api/videos/generate", {"title": "Demo", "prompt": "too short"}, token
        )
        self.assertTrue(status.startswith("400"))
        self.assertIn("Prompt must be", data["detail"])

        status, video = self.request(
            "POST",
            "/api/videos/generate",
            {"title": "Demo", "prompt": "A cinematic sunset over a calm ocean"},
            token,
        )
        self.assertTrue(status.startswith("201"))
        self.assertEqual(video["status"], "pending")

        status, _ = self.request("GET", f"/api/videos/{video['id']}")
        self.assertTrue(status.startswith("401"))

        time.sleep(2.1)
        status, completed_video = self.request("GET", f"/api/videos/{video['id']}", token=token)
        self.assertTrue(status.startswith("200"))
        self.assertEqual(completed_video["status"], "completed")

    def test_password_reset_is_request_only(self):
        status, data = self.request("POST", "/api/auth/reset-password", {"email": "user@example.com"})
        self.assertTrue(status.startswith("202"))
        self.assertIn("reset instructions", data["message"])


if __name__ == "__main__":
    unittest.main()
