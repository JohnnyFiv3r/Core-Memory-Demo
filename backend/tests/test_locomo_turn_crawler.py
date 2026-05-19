import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_turn_crawler import locomo_crawler_callable


class TestLocomoTurnCrawler(unittest.TestCase):
    def test_emits_semantic_association_for_prior_visible_bead(self):
        out = locomo_crawler_callable({
            'request': {
                'turn_id': 'locomo:conv-26:D1:2',
                'user_query': '[LoCoMo replay]',
                'assistant_final': 'Alice talks with Bob about hiking again.',
                'metadata': {'replay_source': 'locomo', 'locomo_dia_id': 'D1:2', 'locomo_speaker': 'Alice'},
            },
            'crawler_context': {
                'beads': [
                    {
                        'id': 'bead-prev',
                        'session_id': 'locomo:conv-26',
                        'source_turn_ids': ['locomo:conv-26:D1:1'],
                        'entities': ['Alice', 'Bob'],
                        'detail': 'Alice and Bob discuss hiking.',
                    },
                    {
                        'id': 'bead-cur',
                        'session_id': 'locomo:conv-26',
                        'source_turn_ids': ['locomo:conv-26:D1:2'],
                        'entities': ['Alice'],
                    },
                ]
            },
        })
        rels = {row['relationship'] for row in out['associations']}
        self.assertEqual({'supports'}, rels)
        self.assertEqual('bead-cur', out['associations'][0]['source_bead_id'])
        self.assertEqual('bead-prev', out['associations'][0]['target_bead_id'])

    def test_uses_current_turn_alias_before_current_bead_exists(self):
        out = locomo_crawler_callable({
            'request': {
                'turn_id': 'locomo:conv-26:D1:2',
                'user_query': '[LoCoMo replay]',
                'assistant_final': 'Bob says Alice should bring hiking boots.',
                'metadata': {'replay_source': 'locomo', 'locomo_dia_id': 'D1:2', 'locomo_speaker': 'Bob'},
            },
            'crawler_context': {
                'beads': [
                    {
                        'id': 'bead-prev',
                        'session_id': 'locomo:conv-26',
                        'source_turn_ids': ['locomo:conv-26:D1:1'],
                        'entities': ['Alice', 'Bob'],
                    }
                ]
            },
        })
        self.assertEqual('__current_turn__', out['associations'][0]['source_bead_id'])
        self.assertEqual('supports', out['associations'][0]['relationship'])

    def test_current_turn_alias_resolves_in_core_memory_contract(self):
        try:
            from core_memory.association.crawler_contract import apply_crawler_updates
            from core_memory.persistence.store import MemoryStore
        except ImportError:
            self.skipTest('core_memory unavailable')

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(td)
            prior = store.add_bead(
                type='context', title='Prior', summary=['Alice and Bob discuss hiking'],
                session_id='locomo:conv-26', source_turn_ids=['locomo:conv-26:D1:1'],
                entities=['Alice', 'Bob'],
            )
            updates = locomo_crawler_callable({
                'request': {
                    'turn_id': 'locomo:conv-26:D1:2',
                    'user_query': '[LoCoMo replay]',
                    'assistant_final': 'Bob says Alice should bring hiking boots.',
                    'metadata': {'replay_source': 'locomo', 'locomo_dia_id': 'D1:2', 'locomo_speaker': 'Bob'},
                },
                'crawler_context': {'beads': [{'id': prior, 'source_turn_ids': ['locomo:conv-26:D1:1'], 'entities': ['Alice', 'Bob']}]},
            })

            out = apply_crawler_updates(
                root=td,
                session_id='locomo:conv-26',
                updates=updates,
                visible_bead_ids=[prior],
            )
            self.assertTrue(out.get('ok'))
            self.assertGreaterEqual(int(out.get('associations_appended') or 0), 1)
            self.assertEqual(0, int(out.get('associations_quarantined') or 0))

    def test_ignores_non_locomo_turns(self):
        self.assertEqual({}, locomo_crawler_callable({'request': {'metadata': {}}, 'crawler_context': {}}))


if __name__ == '__main__':
    unittest.main()
