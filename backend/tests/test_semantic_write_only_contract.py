import ast
import unittest
from pathlib import Path


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "app" / "core" / "runtime.py"


def _func_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    return ""


class TestSemanticWriteOnlyContract(unittest.TestCase):
    def test_build_on_read_default_disabled(self):
        text = RUNTIME_PATH.read_text(encoding="utf-8")
        self.assertIn('os.environ.setdefault("CORE_MEMORY_SEMANTIC_BUILD_ON_READ", "0")', text)

    def test_run_chat_uses_write_sync_hook_not_direct_read_sync(self):
        tree = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
        run_chat = next(
            n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_chat"
        )

        sync_lines = []
        direct_run_async_lines = []
        diag_execute_lines = []

        for n in ast.walk(run_chat):
            if not isinstance(n, ast.Call):
                continue
            name = _func_name(n)
            if name == "_sync_semantic_on_write":
                sync_lines.append(n.lineno)
            elif name == "run_async_jobs":
                direct_run_async_lines.append(n.lineno)
            elif name == "memory_tools.execute":
                # diagnostics retrieval call uses `req` variable
                if n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "req":
                    diag_execute_lines.append(n.lineno)

        self.assertTrue(sync_lines, "run_chat should call _sync_semantic_on_write")
        self.assertFalse(direct_run_async_lines, "run_chat should not call run_async_jobs directly")
        self.assertTrue(diag_execute_lines, "run_chat should execute diagnostics retrieval with req")
        self.assertLess(min(sync_lines), min(diag_execute_lines), "write sync should happen before diagnostics retrieval")

    def test_write_sync_hook_runs_semantic_only_pass(self):
        tree = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
        hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_sync_semantic_on_write")

        found = False
        for n in ast.walk(hook):
            if not isinstance(n, ast.Call) or _func_name(n) != "run_async_jobs":
                continue
            kwargs = {kw.arg: kw.value for kw in n.keywords if kw.arg}
            if (
                isinstance(kwargs.get("run_semantic"), ast.Constant)
                and kwargs["run_semantic"].value is True
                and isinstance(kwargs.get("max_compaction"), ast.Constant)
                and kwargs["max_compaction"].value == 0
                and isinstance(kwargs.get("max_side_effects"), ast.Constant)
                and kwargs["max_side_effects"].value == 0
            ):
                found = True
                break

        self.assertTrue(found, "_sync_semantic_on_write should run semantic-only async pass")


if __name__ == "__main__":
    unittest.main()
