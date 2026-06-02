import unittest

from app.core.runtime import _infer_seed_bead_type, _seed_crawler_updates

try:
    from core_memory.persistence.store_validation_helpers import required_field_issues_for_store
except Exception:  # pragma: no cover - core_memory not installed
    required_field_issues_for_store = None


# Queries that, pre-#175, the heuristic mapped to goal / outcome / evidence /
# checkpoint — types whose now-required fields a single chat line can't supply.
_PREVIOUSLY_NONCONFORMANT = [
    "the goal is to ship the milestone next week",
    "we plan to target the objective",
    "the outcome: we completed and shipped it",
    "show me the evidence and proof of why it supports this",
    "create a checkpoint and flush the session",
]

_ALLOWED_SEED_TYPES = {"context", "decision", "lesson"}


class TestSeedBeadConformance(unittest.TestCase):
    def test_inferred_type_restricted_to_conformant_set(self):
        # CM #175: the seed path may only emit types whose required fields its
        # payload (because / entities / supporting_facts) populates.
        for q in _PREVIOUSLY_NONCONFORMANT + ["a decision: we chose pgvector", "lesson learned today", ""]:
            self.assertIn(_infer_seed_bead_type(q), _ALLOWED_SEED_TYPES, msg=q)

    def test_seed_payload_passes_core_memory_required_fields(self):
        if required_field_issues_for_store is None:
            self.skipTest("core_memory unavailable")
        queries = _PREVIOUSLY_NONCONFORMANT + [
            "we decided to adopt the new caching policy",
            "lesson learned: cap the connection pool",
            "just some background context about the deploy",
        ]
        for q in queries:
            payload = _seed_crawler_updates(user_query=q, turn_id="turn-1")["beads_create"][0]
            # Mirror the baseline fields store.add_bead() stamps on every bead so
            # the validator only exercises the type-specific requirements.
            bead = {**payload, "session_id": "demo-seed", "status": "open", "created_at": "2026-06-02T00:00:00Z"}
            self.assertEqual([], required_field_issues_for_store(bead), msg=f"{q} -> {payload.get('type')}")


if __name__ == "__main__":
    unittest.main()
