import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_suite import build_locomo_suite_metadata


class _Meta:
    def to_dict(self):
        return {'dataset_path': 'fake-locomo.json', 'samples': 2, 'qa_total': 10}


def _sample(sample_id, categories):
    return {
        'sample_id': sample_id,
        'sessions': [],
        'qa': [
            {
                'qa_id': f'{sample_id}:q{i:04d}',
                'category': cat,
                'question': f'question {sample_id} {i}',
                'answer': f'answer {sample_id} {i}',
                'evidence': [f'D{i}:1'],
            }
            for i, cat in enumerate(categories, start=1)
        ],
    }


class TestLocomoSuiteSelection(unittest.TestCase):
    def test_qa_per_category_selects_stratified_caps_across_samples(self):
        samples = [
            _sample('conv-a', [1, 1, 2, 3, 4, 5]),
            _sample('conv-b', [1, 2, 2, 3, 4, 4, 5]),
        ]
        with patch('app.benchmarks.locomo_suite.load_locomo_dataset', return_value=(samples, _Meta())):
            meta, cases, selected_samples, _gold = build_locomo_suite_metadata(
                suite='locomo_retrieval',
                sample_limit=2,
                category_filter=[1, 2, 3, 4, 5],
                qa_per_category={1: 2, '2': 2, 3: 1, 4: 2, 5: 1},
            )

        self.assertEqual(['conv-a', 'conv-b'], [s['sample_id'] for s in selected_samples])
        self.assertEqual([1, 1, 2, 2, 3, 4, 4, 5], [c['category'] for c in cases])
        self.assertEqual(
            ['conv-a', 'conv-b', 'conv-a', 'conv-b', 'conv-a', 'conv-a', 'conv-b', 'conv-a'],
            [c['sample_id'] for c in cases],
        )
        self.assertEqual(
            {'1': 2, '2': 2, '3': 1, '4': 2, '5': 1},
            meta['dataset']['selected_qa_by_category'],
        )
        self.assertEqual('stratified_by_category', meta['dataset']['selection_strategy'])
        self.assertEqual(8, meta['dataset']['selected_qa_cases'])
        self.assertEqual({'conv-a': 5, 'conv-b': 3}, meta['dataset']['selected_qa_by_sample'])

    def test_category_filter_limits_qa_per_category_scope(self):
        samples = [_sample('conv-a', [1, 2, 3, 4, 5])]
        with patch('app.benchmarks.locomo_suite.load_locomo_dataset', return_value=(samples, _Meta())):
            meta, cases, _selected_samples, _gold = build_locomo_suite_metadata(
                suite='locomo_retrieval',
                category_filter=[1, 3],
                qa_per_category={1: 5, 2: 5, 3: 5},
            )

        self.assertEqual([1, 3], [c['category'] for c in cases])
        self.assertEqual({'1': 1, '3': 1}, meta['dataset']['selected_qa_by_category'])
        self.assertEqual([1, 3], meta['dataset']['category_filter'])


if __name__ == '__main__':
    unittest.main()
