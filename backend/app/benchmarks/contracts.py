from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchmarkTurn:
    """Normalized benchmark source turn.

    This is intentionally benchmark-agnostic: dataset adapters preserve source
    identity in metadata while lifecycle runners decide how to replay the turn
    through Core Memory hooks.
    """

    turn_id: str
    speaker: str
    role: str
    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkQA:
    """Normalized benchmark QA item attached to a conversation."""

    qa_id: str
    question: str
    expected_answer: str | None = None
    gold_evidence: list[str] = field(default_factory=list)
    category: str | None = None
    bucket_labels: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkConversation:
    """Normalized benchmark conversation consumed by lifecycle runners."""

    benchmark_name: str
    conversation_id: str
    session_id: str
    turns: list[BenchmarkTurn]
    qa_cases: list[BenchmarkQA]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkShortcutFlags:
    """Flags that distinguish faithful lifecycle runs from fixture/demo modes."""

    synthetic_crawler_updates: bool = False
    synthetic_temporal_edges: bool = False
    bead_direct_ingest: bool = False
    oracle_gold_used: bool = False
    benchmark_aware_answer_prompt: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "synthetic_crawler_updates": self.synthetic_crawler_updates,
            "synthetic_temporal_edges": self.synthetic_temporal_edges,
            "bead_direct_ingest": self.bead_direct_ingest,
            "oracle_gold_used": self.oracle_gold_used,
            "benchmark_aware_answer_prompt": self.benchmark_aware_answer_prompt,
        }

    def any_enabled(self) -> bool:
        return any(self.to_dict().values())


class BenchmarkLifecycleError(RuntimeError):
    pass


def assert_lifecycle_faithful_mode(*, dataset_mode: str, shortcut_flags: BenchmarkShortcutFlags) -> None:
    """Fail fast when authoritative lifecycle mode is contaminated by shortcuts."""

    if str(dataset_mode or "").strip() != "locomo_native_lifecycle":
        return
    if shortcut_flags.any_enabled():
        enabled = ",".join(k for k, v in shortcut_flags.to_dict().items() if v)
        raise BenchmarkLifecycleError(f"faithful mode forbids benchmark shortcuts:{enabled}")
