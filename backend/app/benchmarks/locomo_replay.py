from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from core_memory.integrations.openclaw.runtime import finalize_and_process_turn
except Exception:  # pragma: no cover
    finalize_and_process_turn = None  # type: ignore
try:
    from core_memory.runtime.engine import emit_turn_finalized, process_flush
except Exception:  # pragma: no cover
    emit_turn_finalized = None  # type: ignore
    process_flush = None  # type: ignore
try:
    from core_memory.runtime.passes.association_pass import run_association_pass
except Exception:  # pragma: no cover
    run_association_pass = None  # type: ignore
try:
    from core_memory.runtime.queue.worker import process_memory_event
except Exception:  # pragma: no cover
    process_memory_event = None  # type: ignore

from app.benchmarks.locomo_ingest import _archive_locomo_turn


_LOCOMO_CRAWLER_CALLABLE = 'app.benchmarks.locomo_turn_crawler:locomo_crawler_callable'


_LOCOMO_ENTITY_STOP = {
    'locomo', 'replay', 'session', 'speaker', 'turn', 'dia', 'hey', 'hello', 'hi',
    'good', 'great', 'thanks', 'thank', 'anything', 'what', 'when', 'where', 'why',
    'how', 'the', 'and', 'with', 'from', 'that', 'this', 'there', 'here',
}


def _turn_metadata(*, sample_id: str, session_index: int, session_date_time: str, turn_index: int, dia_id: str, speaker: str, img_url: str, blip_caption: str) -> dict[str, Any]:
    return {
        'benchmark_name': 'locomo',
        'sample_id': sample_id,
        'session_index': session_index,
        'session_date_time': session_date_time,
        'dia_id': dia_id,
        'dia_ids': [dia_id] if dia_id else [],
        'speaker': speaker,
        'turn_index': turn_index,
        'locomo_sample_id': sample_id,
        'locomo_session_index': session_index,
        'locomo_session_date_time': session_date_time,
        'locomo_dia_id': dia_id,
        'locomo_dia_ids': [dia_id] if dia_id else [],
        'locomo_speaker': speaker,
        'locomo_turn_index': turn_index,
        'locomo_has_image': bool(img_url or blip_caption),
        'img_url': img_url,
        'blip_caption': blip_caption,
        'replay_source': 'locomo',
        'replay_policy': 'narrator_single_turn',
    }


def _turn_envelope(*, sample_id: str, session_index: int, turn: dict[str, Any]) -> dict[str, Any]:
    dia_id = str(turn.get('dia_id') or '').strip()
    speaker = str(turn.get('speaker') or '').strip()
    text = str(turn.get('text') or '').strip()
    session_date_time = str(turn.get('session_date_time') or turn.get('date_time') or '').strip()
    turn_index = int(turn.get('turn_index') or 0)
    img_url = str(turn.get('img_url') or '').strip()
    blip_caption = str(turn.get('blip_caption') or '').strip()
    turn_id = f'locomo:{sample_id}:{dia_id}' if dia_id else f'locomo:{sample_id}:turn-{turn_index}'
    metadata = _turn_metadata(
        sample_id=sample_id,
        session_index=session_index,
        session_date_time=session_date_time,
        turn_index=turn_index,
        dia_id=dia_id,
        speaker=speaker,
        img_url=img_url,
        blip_caption=blip_caption,
    )
    assistant_content_parts: list[str] = []
    if session_date_time:
        assistant_content_parts.append(f'Session date: {session_date_time}')
    assistant_content_parts.append(f'{speaker}: {text}'.strip(': '))
    if blip_caption:
        assistant_content_parts.append(f'Image caption: {blip_caption}')
    assistant_content = '\n\n'.join(p for p in assistant_content_parts if p)

    return {
        'session_id': f'locomo:{sample_id}',
        'turn_id': turn_id,
        'transaction_id': f'tx-{turn_id}',
        'trace_id': f'tr-{turn_id}',
        'turns': [
            {
                'speaker': 'benchmark',
                'role': 'user',
                'content': f'[LoCoMo replay] session={session_index} dia_id={dia_id} speaker={speaker}',
            },
            {
                'speaker': speaker or 'assistant',
                'role': 'assistant',
                'content': assistant_content,
            },
        ],
        'trace_depth': 0,
        'origin': 'LOCOMO_REPLAY',
        'tools_trace': [],
        'mesh_trace': [],
        'window_turn_ids': [],
        'window_bead_ids': [],
        'metadata': metadata,
    }


def _read_index(root: str) -> dict[str, Any]:
    path = Path(root) / '.beads' / 'index.json'
    if not path.exists():
        return {'beads': {}, 'associations': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'beads': {}, 'associations': []}
    except Exception:
        return {'beads': {}, 'associations': []}


def _bead_lookup_example(*, bead_id: str, bead: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(bead.get('metadata') or {})
    return {
        'bead_id': str(bead_id or ''),
        'session_id': str(bead.get('session_id') or ''),
        'type': str(bead.get('type') or ''),
        'source_turn_ids': [str(x) for x in list(bead.get('source_turn_ids') or [])[:5]],
        'metadata_turn_id': str(metadata.get('turn_id') or ''),
        'metadata_dia_id': str(metadata.get('dia_id') or ''),
        'metadata_locomo_dia_id': str(metadata.get('locomo_dia_id') or ''),
        'metadata_dia_ids': [str(x) for x in list(metadata.get('dia_ids') or [])[:5]],
        'metadata_locomo_dia_ids': [str(x) for x in list(metadata.get('locomo_dia_ids') or [])[:5]],
    }


def _bead_for_turn(*, index: dict[str, Any], session_id: str, turn_id: str, dia_id: str = '', debug_misses: list[dict[str, Any]] | None = None) -> str:
    wanted = {str(turn_id or '').strip(), str(dia_id or '').strip()}
    wanted = {x for x in wanted if x}
    candidates: list[tuple[str, str]] = []
    same_session_examples: list[dict[str, Any]] = []
    any_session_examples: list[dict[str, Any]] = []
    session_bead_count = 0
    total_bead_count = 0
    for bead_id, bead in dict(index.get('beads') or {}).items():
        if not isinstance(bead, dict):
            continue
        total_bead_count += 1
        if len(any_session_examples) < 3:
            any_session_examples.append(_bead_lookup_example(bead_id=str(bead_id), bead=bead))
        if str(bead.get('session_id') or '') != str(session_id):
            continue
        session_bead_count += 1
        if len(same_session_examples) < 5:
            same_session_examples.append(_bead_lookup_example(bead_id=str(bead_id), bead=bead))
        if str(bead.get('type') or '') == 'process_flush':
            continue
        source_turn_ids = [str(x) for x in list(bead.get('source_turn_ids') or [])]
        metadata = dict(bead.get('metadata') or {})
        metadata_turn_ids = [
            str(metadata.get('turn_id') or ''),
            str(metadata.get('dia_id') or ''),
            str(metadata.get('locomo_dia_id') or ''),
        ]
        for value in list(metadata.get('dia_ids') or []) + list(metadata.get('locomo_dia_ids') or []):
            metadata_turn_ids.append(str(value or ''))
        bead_turn_ids = {str(x).strip() for x in source_turn_ids + metadata_turn_ids if str(x).strip()}
        if wanted.isdisjoint(bead_turn_ids):
            continue
        candidates.append((str(bead.get('created_at') or ''), str(bead_id)))
    candidates.sort()
    if candidates:
        return candidates[0][1]
    if debug_misses is not None and len(debug_misses) < 5:
        debug_misses.append({
            'searched_turn_id': str(turn_id or ''),
            'searched_dia_id': str(dia_id or ''),
            'searched_session_id': str(session_id or ''),
            'wanted': sorted(wanted),
            'index_total_beads': total_bead_count,
            'index_session_beads': session_bead_count,
            'same_session_examples': same_session_examples,
            'any_session_examples': any_session_examples,
        })
    return ''


def _entity_key(value: str) -> str:
    return ''.join(ch.lower() for ch in str(value or '') if ch.isalnum())


def _turn_entities(*, index: dict[str, Any], bead_id: str, speaker: str) -> list[str]:
    bead = dict((dict(index.get('beads') or {}).get(str(bead_id)) or {}))
    raw = list(bead.get('entities') or [])
    if speaker:
        raw.append(str(speaker))
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or '').strip()
        key = _entity_key(text)
        if len(key) < 3 or key in _LOCOMO_ENTITY_STOP or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _synthesize_locomo_associations(*, root: str, sample_id: str, session_index: int, turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Queue benchmark-scoped LoCoMo graph edges once turn beads exist.

    The canonical runtime deliberately does not fabricate associations on the
    fallback path. For LoCoMo benchmark ceiling tests we have trusted dataset
    structure, so the replay adapter can provide deterministic crawler-style
    updates: dia_id adjacency plus bounded same-session entity-overlap links.
    """
    session_id = f'locomo:{sample_id}'
    index = _read_index(root)
    ordered: list[dict[str, Any]] = []
    lookup_misses: list[dict[str, Any]] = []
    for turn in sorted(list(turns or []), key=lambda t: int((t or {}).get('turn_index') or 0)):
        dia_id = str((turn or {}).get('dia_id') or '').strip()
        turn_id = f'locomo:{sample_id}:{dia_id}' if dia_id else f"locomo:{sample_id}:turn-{int((turn or {}).get('turn_index') or 0)}"
        bead_id = _bead_for_turn(index=index, session_id=session_id, turn_id=turn_id, dia_id=dia_id, debug_misses=lookup_misses)
        if not bead_id:
            continue
        ordered.append(
            {
                'turn_id': turn_id,
                'dia_id': dia_id,
                'turn_index': int((turn or {}).get('turn_index') or 0),
                'speaker': str((turn or {}).get('speaker') or '').strip(),
                'bead_id': bead_id,
            }
        )

    visible_ids = [str(row.get('bead_id') or '') for row in ordered if str(row.get('bead_id') or '')]
    associations: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_assoc(source: str, target: str, relationship: str, reason: str, confidence: float, reason_code: str, evidence_fields: list[str]) -> None:
        if not source or not target or source == target:
            return
        key = (str(source), str(target), str(relationship))
        if key in seen_edges:
            return
        seen_edges.add(key)
        associations.append(
            {
                'source_bead_id': str(source),
                'target_bead_id': str(target),
                'relationship': str(relationship),
                'reason_text': str(reason),
                'confidence': float(confidence),
                'provenance': 'locomo_replay',
                'reason_code': str(reason_code),
                'evidence_fields': list(evidence_fields),
            }
        )

    # Dia-id/session order links: enough structure for trace traversal to move
    # along the retained conversation timeline without model-authored edges.
    for prev, cur in zip(ordered, ordered[1:]):
        add_assoc(
            str(cur.get('bead_id') or ''),
            str(prev.get('bead_id') or ''),
            'follows',
            f"LoCoMo replay session order: {cur.get('dia_id')} follows retained prior turn {prev.get('dia_id')} in sample {sample_id} session {session_index}.",
            1.0,
            'locomo_session_order',
            ['locomo_sample_id', 'locomo_session_index', 'locomo_dia_id', 'locomo_turn_index'],
        )
        add_assoc(
            str(prev.get('bead_id') or ''),
            str(cur.get('bead_id') or ''),
            'precedes',
            f"LoCoMo replay session order: {prev.get('dia_id')} precedes retained later turn {cur.get('dia_id')} in sample {sample_id} session {session_index}.",
            1.0,
            'locomo_session_order',
            ['locomo_sample_id', 'locomo_session_index', 'locomo_dia_id', 'locomo_turn_index'],
        )

    # Bounded entity-overlap links: connect each turn to the latest previous
    # mentions of the same meaningful people/entities, excluding generic replay
    # scaffolding tokens. The relationship itself stays in the canonical Core
    # Memory vocabulary; the overlap heuristic is recorded as reason metadata.
    latest_by_entity: dict[str, str] = {}
    for cur in ordered:
        cur_bead = str(cur.get('bead_id') or '')
        linked_targets = 0
        entities = _turn_entities(index=index, bead_id=cur_bead, speaker=str(cur.get('speaker') or ''))
        for entity in entities:
            key = _entity_key(entity)
            prior_bead = latest_by_entity.get(key, '')
            if prior_bead and prior_bead != cur_bead:
                add_assoc(
                    cur_bead,
                    prior_bead,
                    'associated_with',
                    f"LoCoMo replay entity overlap: both turns mention {entity!r} within sample {sample_id} session {session_index}.",
                    0.82,
                    'locomo_entity_overlap',
                    ['entities', 'locomo_speaker', 'locomo_session_index'],
                )
                linked_targets += 1
                if linked_targets >= 3:
                    break
        for entity in entities:
            latest_by_entity[_entity_key(entity)] = cur_bead

    if not associations:
        return {
            'ok': True,
            'enabled': True,
            'associations_requested': 0,
            'associations_appended': 0,
            'beads_considered': len(ordered),
            'lookup_misses': lookup_misses,
            'lookup_misses_omitted': max(0, len(list(turns or [])) - len(ordered) - len(lookup_misses)),
        }

    if run_association_pass is None:
        return {
            'ok': False,
            'enabled': False,
            'associations_requested': len(associations),
            'associations_appended': 0,
            'associations_quarantined': 0,
            'beads_considered': len(ordered),
            'lookup_misses': lookup_misses,
            'lookup_misses_omitted': max(0, len(list(turns or [])) - len(ordered) - len(lookup_misses)),
            'reason': 'run_association_pass_unavailable',
        }

    out = run_association_pass(
        root=root,
        session_id=session_id,
        updates={
            'association_scope': 'historical_session',
            'associations': associations,
        },
        visible_bead_ids=visible_ids,
    )
    return {
        'ok': bool((out or {}).get('ok')),
        'enabled': True,
        'beads_considered': len(ordered),
        'associations_requested': len(associations),
        'associations_appended': int((out or {}).get('associations_appended') or 0),
        'associations_quarantined': int((out or {}).get('associations_quarantined') or 0),
        'authority_path': str((out or {}).get('authority_path') or ''),
        'lookup_misses': lookup_misses,
        'lookup_misses_omitted': max(0, len(list(turns or [])) - len(ordered) - len(lookup_misses)),
    }


def replay_locomo_sample(*, root: str, sample: dict[str, Any], mode: str = 'transcript_only', flush_policy: str = 'per_session') -> dict[str, Any]:
    if str(mode or 'transcript_only') == 'canonical_turn':
        if finalize_and_process_turn is None:
            raise RuntimeError('core_memory_unavailable:finalize_and_process_turn')
    else:
        if emit_turn_finalized is None:
            raise RuntimeError('core_memory_unavailable:emit_turn_finalized')
    sample_id = str(sample.get('sample_id') or '').strip()
    sessions = list(sample.get('sessions') or [])
    emitted: list[dict[str, Any]] = []
    skipped_existing = 0
    flushes: list[dict[str, Any]] = []
    association_synthesis: list[dict[str, Any]] = []
    for session in sessions:
        session_index = int((session or {}).get('session_index') or 0)
        session_turns = list((session or {}).get('turns') or [])
        for turn in session_turns:
            env = _turn_envelope(sample_id=sample_id, session_index=session_index, turn=dict(turn or {}))
            if str(mode or 'transcript_only') == 'canonical_turn':
                previous_invoke = os.environ.get('CORE_MEMORY_AGENT_CRAWLER_INVOKE')
                os.environ['CORE_MEMORY_AGENT_CRAWLER_INVOKE'] = '1'
                try:
                    out = finalize_and_process_turn(root=root, policy=None, **env)
                finally:
                    if previous_invoke is None:
                        os.environ.pop('CORE_MEMORY_AGENT_CRAWLER_INVOKE', None)
                    else:
                        os.environ['CORE_MEMORY_AGENT_CRAWLER_INVOKE'] = previous_invoke
                emitted_flag = bool((out or {}).get('processed') or (out or {}).get('ok'))
                emitted_row = (out or {}).get('emitted') or {}
                if emitted_row and not bool(emitted_row.get('emitted', True)):
                    emitted_flag = False
            else:
                out = emit_turn_finalized(root=root, **env)
                event_id = out.get('event_id')
                payload = out.get('payload') or {}
                if payload:
                    worker_out = process_memory_event(root, payload)
                    out = {**out, 'worker': worker_out}
                emitted_flag = bool(out.get('emitted') or event_id)
            if emitted_flag:
                # Explicitly write to the turn archive so the hydration path can
                # retrieve full transcript text by locomo:{sample_id}:{dia_id}
                # regardless of what core_memory's internal processing writes.
                _archive_locomo_turn(root=root, turn=dict(turn or {}))
                emitted.append(
                    {
                        'turn_id': env['turn_id'],
                        'dia_id': str((env.get('metadata') or {}).get('locomo_dia_id') or ''),
                        'session_id': env['session_id'],
                        'status': 'ingested',
                        'trace': dict(env.get('metadata') or {}),
                    }
                )
            else:
                skipped_existing += 1
                emitted.append(
                    {
                        'turn_id': env['turn_id'],
                        'dia_id': str((env.get('metadata') or {}).get('locomo_dia_id') or ''),
                        'session_id': env['session_id'],
                        'status': 'skipped_existing',
                        'trace': dict(env.get('metadata') or {}),
                    }
                )
        if str(mode or 'transcript_only') == 'canonical_turn':
            try:
                association_synthesis.append(_synthesize_locomo_associations(root=root, sample_id=sample_id, session_index=session_index, turns=[dict(t or {}) for t in session_turns]))
            except Exception as exc:
                association_synthesis.append({'ok': False, 'enabled': True, 'step': 'locomo_association_synthesis', 'error': str(exc), 'session_id': f'locomo:{sample_id}'})
        if str(flush_policy or 'per_session') == 'per_session':
            if process_flush is None:
                flushes.append({'ok': False, 'step': 'process_flush', 'error': 'core_memory_unavailable', 'session_id': f'locomo:{sample_id}'})
            else:
                try:
                    flushes.append(process_flush(root=root, session_id=f'locomo:{sample_id}', promote=True, token_budget=128000, max_beads=200, source='locomo_replay'))
                except Exception as exc:
                    flushes.append({'ok': False, 'step': 'process_flush', 'error': str(exc), 'session_id': f'locomo:{sample_id}'})
    if str(flush_policy or 'per_session') == 'end_only':
        if process_flush is None:
            flushes.append({'ok': False, 'step': 'process_flush', 'error': 'core_memory_unavailable', 'session_id': f'locomo:{sample_id}'})
        else:
            try:
                flushes.append(process_flush(root=root, session_id=f'locomo:{sample_id}', promote=True, token_budget=128000, max_beads=200, source='locomo_replay'))
            except Exception as exc:
                flushes.append({'ok': False, 'step': 'process_flush', 'error': str(exc), 'session_id': f'locomo:{sample_id}'})
    return {
        'ok': True,
        'sample_id': sample_id,
        'mode': str(mode or 'transcript_only'),
        'flush_policy': str(flush_policy or 'per_session'),
        'turns_total': sum(len((s or {}).get('turns') or []) for s in sessions),
        'ingested': emitted,
        'ingested_count': sum(1 for row in emitted if row.get('status') == 'ingested'),
        'skipped_existing_count': skipped_existing,
        'association_synthesis': {
            'enabled': str(mode or 'transcript_only') == 'canonical_turn',
            'sessions': association_synthesis,
            'associations_requested': sum(int((row or {}).get('associations_requested') or 0) for row in association_synthesis),
            'associations_appended': sum(int((row or {}).get('associations_appended') or 0) for row in association_synthesis),
            'associations_quarantined': sum(int((row or {}).get('associations_quarantined') or 0) for row in association_synthesis),
        },
        'flushes': flushes,
    }
