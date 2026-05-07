import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

from app.benchmarks.locomo_ingest import ingest_locomo_turns


def _sample(sample_id: str):
    return {
        'sample_id': sample_id,
        'sessions': [
            {
                'turns': [
                    {
                        'sample_id': sample_id,
                        'session_index': 1,
                        'turn_index': 1,
                        'dia_id': 'D1:1',
                        'speaker': 'A',
                        'text': f'hello from {sample_id}',
                        'session_date_time': '2023-01-01 10:00',
                    },
                    {
                        'sample_id': sample_id,
                        'session_index': 1,
                        'turn_index': 2,
                        'dia_id': 'D1:2',
                        'speaker': 'B',
                        'text': f'reply from {sample_id}',
                        'session_date_time': '2023-01-01 10:01',
                    },
                ]
            }
        ],
    }


class TestLocomoIngestSampleScope(unittest.TestCase):
    def test_repeated_dia_ids_are_scoped_by_sample(self):
        with tempfile.TemporaryDirectory() as td:
            first = ingest_locomo_turns(root=td, sample=_sample('conv-a'))
            second = ingest_locomo_turns(root=td, sample=_sample('conv-b'))

            self.assertEqual(2, first['ingested_count'])
            self.assertEqual(0, first['skipped_existing_count'])
            self.assertEqual(2, second['ingested_count'])
            self.assertEqual(0, second['skipped_existing_count'])

            idx = json.loads((Path(td) / '.beads' / 'index.json').read_text(encoding='utf-8'))
            sessions = sorted({row.get('session_id') for row in (idx.get('beads') or {}).values()})
            self.assertIn('locomo:conv-a', sessions)
            self.assertIn('locomo:conv-b', sessions)


if __name__ == '__main__':
    unittest.main()
