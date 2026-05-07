import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

if importlib.util.find_spec('pydantic_settings') is not None:
    from app.benchmarks import locomo_replay as locomo_replay_mod
    from app.benchmarks.locomo_replay import replay_locomo_sample
    from core_memory.runtime.turn_archive import find_turn_record, get_adjacent_turns
else:
    replay_locomo_sample = None
    find_turn_record = None
    get_adjacent_turns = None


def _project_dia_ids(metadata: dict, source_turn_ids: list[str] | None = None) -> list[str]:
    raw_dia_ids = []
    dia_id_source = ''
    for key in ('dia_ids', 'dia_id', 'locomo_dia_ids', 'locomo_dia_id'):
        value = metadata.get(key)
        if isinstance(value, list):
            raw_dia_ids.extend([str(x).strip() for x in value if str(x).strip()])
            if raw_dia_ids and not dia_id_source:
                dia_id_source = f'metadata.{key}'
        elif str(value or '').strip():
            raw_dia_ids.append(str(value).strip())
            if raw_dia_ids and not dia_id_source:
                dia_id_source = f'metadata.{key}'
    if not raw_dia_ids:
        raw_dia_ids.extend([str(x).strip() for x in (source_turn_ids or []) if str(x).strip().startswith('D')])
    return sorted(set(x for x in raw_dia_ids if x))


class TestLocomoReplay(unittest.TestCase):
    def _sample(self):
        return {
            'sample_id': 'conv-26',
            'sessions': [
                {
                    'session_index': 1,
                    'date_time': '1 Jan 2024',
                    'turns': [
                        {
                            'sample_id': 'conv-26',
                            'session_index': 1,
                            'turn_index': 1,
                            'dia_id': 'D1:1',
                            'speaker': 'Alice',
                            'text': 'Hello there',
                            'session_date_time': '1 Jan 2024',
                        },
                        {
                            'sample_id': 'conv-26',
                            'session_index': 1,
                            'turn_index': 2,
                            'dia_id': 'D1:2',
                            'speaker': 'Bob',
                            'text': 'Hi back',
                            'session_date_time': '1 Jan 2024',
                        },
                    ],
                }
            ],
            'qa': [],
        }

    def test_replay_emits_turn_with_dia_id_metadata(self):
        if replay_locomo_sample is None or find_turn_record is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            out = replay_locomo_sample(root=td, sample=self._sample(), mode='transcript_only', flush_policy='end_only')
            self.assertEqual(2, out['ingested_count'])
            row = find_turn_record(root=Path(td), turn_id='locomo:conv-26:D1:1', session_id='locomo:conv-26')
            self.assertIsNotNone(row)
            self.assertEqual('D1:1', ((row or {}).get('metadata') or {}).get('locomo_dia_id'))

    def test_replay_is_idempotent(self):
        if replay_locomo_sample is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            out1 = replay_locomo_sample(root=td, sample=self._sample(), mode='transcript_only', flush_policy='end_only')
            out2 = replay_locomo_sample(root=td, sample=self._sample(), mode='transcript_only', flush_policy='end_only')
            self.assertEqual(2, out1['ingested_count'])
            self.assertEqual(0, out2['ingested_count'])
            self.assertEqual(2, out2['skipped_existing_count'])

    def test_replay_preserves_session_ordering(self):
        if replay_locomo_sample is None or get_adjacent_turns is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            replay_locomo_sample(root=td, sample=self._sample(), mode='transcript_only', flush_policy='end_only')
            around = get_adjacent_turns(root=Path(td), turn_id='locomo:conv-26:D1:2', session_id='locomo:conv-26', before=1, after=0)
            self.assertIsNotNone(around)
            self.assertEqual('locomo:conv-26:D1:1', (((around or {}).get('before') or [{}])[-1]).get('turn_id'))

    def test_project_retrieval_back_to_dia_id(self):
        metadata = {
            'sample_id': 'conv-26',
            'session_index': 1,
            'speaker': 'Alice',
            'session_date_time': '1 Jan 2024',
            'locomo_dia_id': 'D1:1',
        }
        self.assertEqual(['D1:1'], _project_dia_ids(metadata, []))

    def test_canonical_replay_synthesizes_locomo_associations(self):
        if replay_locomo_sample is None:
            self.skipTest('pydantic_settings unavailable')
        sample = self._sample()
        sample['sessions'][0]['turns'][0]['text'] = 'Alice and Bob discuss hiking plans.'
        sample['sessions'][0]['turns'][1]['text'] = 'Bob confirms the hiking plan with Alice.'
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'CORE_MEMORY_ENRICHMENT_QUEUE': '0'}):
            out = replay_locomo_sample(root=td, sample=sample, mode='canonical_turn', flush_policy='end_only')
            index = json.loads((Path(td) / '.beads' / 'index.json').read_text())

        self.assertTrue(out['association_synthesis']['enabled'])
        self.assertGreaterEqual(out['association_synthesis']['associations_requested'], 2)
        self.assertGreaterEqual(out['association_synthesis']['associations_appended'], 2)
        relationships = {str(row.get('relationship') or '') for row in list(index.get('associations') or [])}
        self.assertIn('follows', relationships)
        self.assertIn('precedes', relationships)

    def test_synthesized_entity_overlap_relationship_counts_as_semantic(self):
        if replay_locomo_sample is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.beads').mkdir(parents=True)
            (root / '.beads' / 'index.json').write_text(json.dumps({
                'beads': {
                    'b1': {'entities': ['Alice'], 'session_id': 'locomo:conv-26', 'source_turn_ids': ['D1:1']},
                    'b2': {'entities': ['Alice'], 'session_id': 'locomo:conv-26', 'metadata': {'locomo_dia_id': 'D1:2'}},
                },
                'associations': [],
            }), encoding='utf-8')
            captured = {}

            def fake_run_association_pass(**kwargs):
                captured.update(kwargs)
                return {'ok': True, 'associations_appended': len(kwargs['updates']['associations'])}

            turns = [
                {'bead_id': 'b1', 'dia_id': 'D1:1', 'turn_index': 1, 'speaker': 'Alice'},
                {'bead_id': 'b2', 'dia_id': 'D1:2', 'turn_index': 2, 'speaker': 'Alice'},
            ]
            with patch.object(locomo_replay_mod, 'run_association_pass', side_effect=fake_run_association_pass):
                out = locomo_replay_mod._synthesize_locomo_associations(root=str(root), sample_id='conv-26', session_index=1, turns=turns)

        relationships = {row['relationship'] for row in captured['updates']['associations']}
        self.assertIn('entity_overlap', relationships)
        self.assertNotIn('associated_with', relationships)
        self.assertGreaterEqual(out['associations_requested'], 3)

    def test_synthesis_reports_lookup_miss_examples(self):
        if replay_locomo_sample is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.beads').mkdir(parents=True)
            (root / '.beads' / 'index.json').write_text(json.dumps({
                'beads': {
                    'b-other': {'type': 'context', 'session_id': 'locomo:conv-26', 'source_turn_ids': ['unexpected']},
                },
                'associations': [],
            }), encoding='utf-8')
            out = locomo_replay_mod._synthesize_locomo_associations(
                root=str(root),
                sample_id='conv-26',
                session_index=1,
                turns=[{'dia_id': 'D1:1', 'turn_index': 1, 'speaker': 'Alice'}],
            )

        miss = out['lookup_misses'][0]
        self.assertEqual('locomo:conv-26:D1:1', miss['searched_turn_id'])
        self.assertEqual('D1:1', miss['searched_dia_id'])
        self.assertEqual('locomo:conv-26', miss['searched_session_id'])
        self.assertEqual(1, miss['index_session_beads'])
        self.assertEqual('b-other', miss['same_session_examples'][0]['bead_id'])
        self.assertEqual(['unexpected'], miss['same_session_examples'][0]['source_turn_ids'])


if __name__ == '__main__':
    unittest.main()
