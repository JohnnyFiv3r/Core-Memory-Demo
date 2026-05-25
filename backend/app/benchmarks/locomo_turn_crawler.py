from __future__ import annotations

import re
from typing import Any

_STOP = {
    'locomo', 'replay', 'session', 'speaker', 'turn', 'dia', 'hey', 'hello', 'hi',
    'good', 'great', 'thanks', 'thank', 'anything', 'what', 'when', 'where', 'why',
    'how', 'the', 'and', 'with', 'from', 'that', 'this', 'there', 'here', 'you', 'your',
    'our', 'their', 'they', 'them', 'for', 'are', 'was', 'were', 'have', 'has', 'had',
}


def _entity_key(value: str) -> str:
    return ''.join(ch.lower() for ch in str(value or '') if ch.isalnum())


def _text_entities(*texts: str, speaker: str = '') -> list[str]:
    raw: list[str] = []
    if speaker:
        raw.append(str(speaker))
    for text in texts:
        s = str(text or '')
        raw.extend(m.group(1) for m in re.finditer(r"\b([A-Z][A-Za-z0-9._-]{2,}|[A-Z]{2,}[A-Za-z0-9._-]*)\b", s))
        if not raw:
            raw.extend(m.group(0) for m in re.finditer(r"\b[a-zA-Z][a-zA-Z0-9_-]{3,}\b", s))
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or '').strip().strip('.,:;!?()[]{}"\'')
        key = _entity_key(text)
        if len(key) < 3 or key in _STOP or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= 12:
            break
    return out


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get('id') or row.get('bead_id') or '').strip()


def _row_turn_ids(row: dict[str, Any]) -> set[str]:
    out = {str(x).strip() for x in list(row.get('source_turn_ids') or []) if str(x).strip()}
    md = dict(row.get('metadata') or {})
    for key in ('turn_id', 'dia_id', 'locomo_dia_id'):
        if str(md.get(key) or '').strip():
            out.add(str(md.get(key)).strip())
    for key in ('dia_ids', 'locomo_dia_ids'):
        for value in list(md.get(key) or []):
            if str(value or '').strip():
                out.add(str(value).strip())
    return out


def _row_entities(row: dict[str, Any]) -> set[str]:
    ents = [str(x) for x in list(row.get('entities') or [])]
    if not ents:
        ents = _text_entities(str(row.get('title') or ''), str(row.get('detail') or ''), ' '.join(str(x) for x in list(row.get('summary') or [])))
    return {_entity_key(x) for x in ents if _entity_key(x)}


def locomo_crawler_callable(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic benchmark crawler for LoCoMo canonical replay.

    This is intentionally lightweight: it does not pretend to be the final LLM
    causality agent. It provides turn-time semantic coverage for benchmark
    replay by linking the current turn bead to prior visible beads through
    concrete entity/topic overlap, so the Core-Memory gate and trace machinery
    exercise the real per-turn association contract.
    """

    req = dict((payload or {}).get('request') or {})
    ctx = dict((payload or {}).get('crawler_context') or {})
    md = dict(req.get('metadata') or {})
    if str(md.get('replay_source') or '') != 'locomo':
        return {}

    turn_id = str(req.get('turn_id') or '').strip()
    dia_id = str(md.get('locomo_dia_id') or '').strip()
    source_turn_ids = [x for x in [turn_id, dia_id] if x]
    speaker = str(md.get('locomo_speaker') or '').strip()
    session_date_time = str(md.get('locomo_session_date_time') or md.get('session_date_time') or '').strip()
    blip_caption = str(md.get('blip_caption') or '').strip()
    user_query = str(req.get('user_query') or '')
    assistant_final = str(req.get('assistant_final') or '')
    # LoCoMo replay rows are multi-speaker dialogue turns with role="other",
    # so the canonical user/assistant compatibility fields are often empty.
    # Use turn_text as the semantic source; otherwise every replay row degrades
    # to the same generic "LoCoMo replay turn" bead and write de-dupe collapses
    # the corpus to a single bead.
    turn_text = str(req.get('turn_text') or '')
    source_text = assistant_final or user_query or turn_text
    current_entities = {_entity_key(x) for x in _text_entities(source_text, speaker=speaker)}

    rows = [dict(r or {}) for r in list(ctx.get('beads') or []) if isinstance(r, dict)]
    current = None
    for row in reversed(rows):
        ids = _row_turn_ids(row)
        if turn_id and turn_id in ids:
            current = row
            break
        if dia_id and dia_id in ids:
            current = row
            break
    # The turn crawler is invoked before Core-Memory persists the current turn
    # creation row, so the current bead id usually is not known yet. Core-Memory
    # resolves this alias to the bead created by this same update batch.
    current_id = _row_id(current or {}) or '__current_turn__'

    associations: list[dict[str, Any]] = []
    prior_rows = [r for r in rows if _row_id(r) and _row_id(r) != current_id]
    if prior_rows:
        prev = prior_rows[-1]
        associations.append({
            'source_bead_id': current_id,
            'target_bead_id': _row_id(prev),
            'relationship': 'supports',
            'reason_text': 'LoCoMo replay turn has same-session continuity with the prior visible turn.',
            'confidence': 0.72,
            'provenance': 'agent_callable',
            'reason_code': 'locomo_turn_adjacency',
            'evidence_fields': ['locomo_dia_id', 'locomo_turn_index'],
        })

    linked = 0
    for prior in reversed(prior_rows):
        overlap = current_entities.intersection(_row_entities(prior))
        if not overlap:
            continue
        associations.append({
            'source_bead_id': current_id,
            'target_bead_id': _row_id(prior),
            'relationship': 'supports',
            'reason_text': 'LoCoMo replay turn shares concrete entity/topic mentions with a prior visible turn.',
            'confidence': 0.82,
            'provenance': 'agent_callable',
            'reason_code': 'locomo_entity_overlap',
            'evidence_fields': ['assistant_final', 'entities', 'locomo_speaker'],
        })
        linked += 1
        if linked >= 3:
            break

    title = (source_text or 'LoCoMo replay turn').splitlines()[0][:160]
    detail_parts: list[str] = []
    if session_date_time:
        detail_parts.append(f'Session date: {session_date_time}')
    detail_parts.append(source_text[:1200])
    if blip_caption:
        detail_parts.append(f'Image caption: {blip_caption}')
    bead_detail = '\n\n'.join(p for p in detail_parts if p)
    return {
        'beads_create': [{
            'type': 'context',
            'title': title or 'LoCoMo replay turn',
            'summary': [(source_text or 'LoCoMo replay turn')[:240]],
            'detail': bead_detail,
            'source_turn_ids': source_turn_ids,
            'entities': sorted(x for x in current_entities if x)[:12],
            'topics': [x for x in ['locomo', speaker] if x][:8],
            'supporting_facts': [source_text[:240]] if source_text else [],
            'retrieval_eligible': True,
            'retrieval_title': title or 'LoCoMo replay turn',
            'retrieval_facts': [source_text[:240]] if source_text else [],
            'tags': ['crawler_reviewed', 'turn_finalized', 'locomo_replay', 'agent_authored_semantic'],
        }],
        'associations': associations,
    }
