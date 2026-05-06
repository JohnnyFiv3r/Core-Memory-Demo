from __future__ import annotations

from typing import Any

from core_memory.integrations.openclaw_runtime import finalize_and_process_turn
from core_memory.runtime.engine import emit_turn_finalized, process_flush
from core_memory.runtime.worker import process_memory_event


def _turn_metadata(*, sample_id: str, session_index: int, session_date_time: str, turn_index: int, dia_id: str, speaker: str, img_url: str, blip_caption: str) -> dict[str, Any]:
    return {
        'benchmark_name': 'locomo',
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
    return {
        'session_id': f'locomo:{sample_id}',
        'turn_id': turn_id,
        'transaction_id': f'tx-{turn_id}',
        'trace_id': f'tr-{turn_id}',
        'user_query': f'[LoCoMo replay] session={session_index} dia_id={dia_id} speaker={speaker}',
        'assistant_final': f'{speaker}: {text}'.strip(': '),
        'trace_depth': 0,
        'origin': 'LOCOMO_REPLAY',
        'tools_trace': [],
        'mesh_trace': [],
        'window_turn_ids': [],
        'window_bead_ids': [],
        'metadata': metadata,
    }


def replay_locomo_sample(*, root: str, sample: dict[str, Any], mode: str = 'transcript_only', flush_policy: str = 'per_session') -> dict[str, Any]:
    sample_id = str(sample.get('sample_id') or '').strip()
    sessions = list(sample.get('sessions') or [])
    emitted: list[dict[str, Any]] = []
    skipped_existing = 0
    flushes: list[dict[str, Any]] = []
    for session in sessions:
        session_index = int((session or {}).get('session_index') or 0)
        for turn in list((session or {}).get('turns') or []):
            env = _turn_envelope(sample_id=sample_id, session_index=session_index, turn=dict(turn or {}))
            if str(mode or 'transcript_only') == 'canonical_turn':
                out = finalize_and_process_turn(root=root, policy=None, **env)
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
        if str(flush_policy or 'per_session') == 'per_session':
            try:
                flushes.append(process_flush(root=root, session_id=f'locomo:{sample_id}', promote=True, token_budget=128000, max_beads=200, source='locomo_replay'))
            except Exception as exc:
                flushes.append({'ok': False, 'step': 'process_flush', 'error': str(exc), 'session_id': f'locomo:{sample_id}'})
    if str(flush_policy or 'per_session') == 'end_only':
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
        'flushes': flushes,
    }
