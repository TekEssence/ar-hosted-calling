"""Dependency-free tests of /ready without loading GPU models or app secrets."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


class Response:
    def __init__(self, content, status_code):
        self.content = content
        self.status_code = status_code


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "server/routes/misc.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "ready")
        node.decorator_list = []
        self.state = {
            "stt_model": object(), "llm_model": "test-model",
            "redis": SimpleNamespace(ping=AsyncMock(return_value=True)),
            "llm_client": SimpleNamespace(models=SimpleNamespace(list=AsyncMock(
                return_value=SimpleNamespace(data=[SimpleNamespace(id="test-model")])))),
        }
        namespace = {"asyncio": asyncio, "state": self.state, "JSONResponse": Response}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        self.ready = namespace["ready"]

    async def test_ready(self):
        response = await self.ready()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(response.content["checks"].values()))

    async def test_redis_failure(self):
        self.state["redis"].ping.side_effect = ConnectionError()
        response = await self.ready()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.content["checks"]["redis"])

    async def test_wrong_model(self):
        self.state["llm_model"] = "not-loaded"
        response = await self.ready()
        self.assertEqual(response.status_code, 503)

    async def test_llm_failure(self):
        self.state["llm_client"].models.list.side_effect = TimeoutError()
        self.assertEqual((await self.ready()).status_code, 503)

    async def test_whisper_missing(self):
        self.state["stt_model"] = None
        self.assertEqual((await self.ready()).status_code, 503)


if __name__ == "__main__":
    unittest.main()
