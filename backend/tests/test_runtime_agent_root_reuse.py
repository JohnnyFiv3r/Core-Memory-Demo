import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent_runtime import run_agent_for_root


class TestRuntimeAgentRootReuse(unittest.TestCase):
    def test_run_agent_for_root_uses_requested_root_and_session(self):
        async def _fake_run_with_memory(agent, message, *, root, session_id, turn_id, metadata):
            self.assertEqual('/tmp/bench-root', root)
            self.assertEqual('locomo:conv-1', session_id)
            self.assertEqual('When?', message)
            self.assertEqual('core_memory_demo_benchmark', metadata.get('source'))
            return type('R', (), {'output': 'Bench answer'})()

        with patch('app.core.agent_runtime.create_agent_for_root') as create_agent, patch('app.core.agent_runtime.run_with_memory', side_effect=_fake_run_with_memory):
            create_agent.return_value = object()
            out = asyncio.run(
                run_agent_for_root(
                    root='/tmp/bench-root',
                    session_id='locomo:conv-1',
                    message='When?',
                    model_id='openai:gpt-4o-mini',
                )
            )

        self.assertTrue(out['ok'])
        self.assertEqual('Bench answer', out['assistant'])
        self.assertEqual('openai:gpt-4o-mini', out['model_id'])


if __name__ == '__main__':
    unittest.main()
