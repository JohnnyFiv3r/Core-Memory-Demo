import sys
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
        self.assertIn('topic_continuation', rels)
        self.assertIn('entity_overlap', rels)
        self.assertEqual('bead-cur', out['associations'][0]['source_bead_id'])
        self.assertEqual('bead-prev', out['associations'][0]['target_bead_id'])

    def test_ignores_non_locomo_turns(self):
        self.assertEqual({}, locomo_crawler_callable({'request': {'metadata': {}}, 'crawler_context': {}}))


if __name__ == '__main__':
    unittest.main()
