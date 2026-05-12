import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestRecallEndpointContractStatic(unittest.TestCase):
    def test_recall_endpoint_route_is_wired(self):
        tree = ast.parse((ROOT / "app" / "routes" / "demo.py").read_text())
        recall_fn = None
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "recall_endpoint":
                recall_fn = node
                break
        self.assertIsNotNone(recall_fn, "demo.py should define recall_endpoint")
        decorators = [ast.unparse(d) for d in recall_fn.decorator_list]
        self.assertTrue(any("router.post('/recall'" in d or 'router.post("/recall"' in d for d in decorators))
        calls = [ast.unparse(n.func) for n in ast.walk(recall_fn) if isinstance(n, ast.Call)]
        self.assertIn("run_recall", calls)

    def test_run_chat_uses_recall_orchestrator_for_diagnostics(self):
        source = (ROOT / "app" / "core" / "runtime.py").read_text()
        tree = ast.parse(source)
        run_chat = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_chat")
        calls = [ast.unparse(n.func) for n in ast.walk(run_chat) if isinstance(n, ast.Call)]
        self.assertIn("run_recall", calls)
        self.assertIn('"source_surface": "recall_orchestrator"', source)
        self.assertIn('"recall_result"', source)
        self.assertIn('"evidence": list(recall_contract.get("evidence") or [])', source)
        self.assertIn('"sources": list(recall_contract.get("sources") or [])', source)
        self.assertIn('"tier_path": list(recall_contract.get("tier_path") or [])', source)

    def test_run_recall_returns_recall_result_contract(self):
        source = (ROOT / "app" / "core" / "runtime.py").read_text()
        tree = ast.parse(source)
        run_recall = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_recall")
        calls = [ast.unparse(n.func) for n in ast.walk(run_recall) if isinstance(n, ast.Call)]
        self.assertIn("core_recall", calls)
        self.assertIn("_recall_result_to_payload", calls)
        self.assertIn("validate_recall_effort", calls)

    def test_frontend_renders_recall_evidence_panel(self):
        js = (ROOT.parent / "frontend" / "public" / "chat-app.js").read_text()
        html = (ROOT.parent / "frontend" / "public" / "chat.html").read_text()
        self.assertIn("function recallContractFromChatPayload", js)
        self.assertIn("function renderRecallEvidence", js)
        self.assertIn("recall-evidence-panel", js)
        self.assertIn("recall-evidence-panel", html)


if __name__ == "__main__":
    unittest.main()
