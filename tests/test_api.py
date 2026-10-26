"""HTTP contract checks used by the pull request workflow."""

import unittest

from fastapi.testclient import TestClient

from main import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_root_reports_running_service(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Reserving API is running."})

    def test_greeting_defaults_to_world(self):
        response = self.client.get("/hello")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Hello, World!"})

    def test_greeting_accepts_supplied_name(self):
        response = self.client.get("/hello", params={"name": "Jane Doe"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Hello, Jane Doe!"})

    def test_greeting_accepts_maximum_name_length(self):
        name = "a" * 100
        response = self.client.get("/hello", params={"name": name})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": f"Hello, {name}!"})

    def test_greeting_rejects_invalid_name_lengths(self):
        for name in ("", "a" * 101):
            with self.subTest(name_length=len(name)):
                response = self.client.get("/hello", params={"name": name})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"][0]["loc"], ["query", "name"])

    def test_health_returns_json(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_openapi_describes_public_get_endpoints(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        for path in ("/", "/hello", "/health"):
            with self.subTest(path=path):
                self.assertIn("get", paths[path])


if __name__ == "__main__":
    unittest.main()
