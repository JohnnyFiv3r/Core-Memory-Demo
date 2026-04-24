from __future__ import annotations

import uuid
from typing import Any

from core_memory.integrations.pydanticai.memory_tools import (
    continuity_prompt,
    memory_execute_tool,
    memory_search_tool,
    memory_trace_tool,
)
from core_memory.integrations.pydanticai.run import run_with_memory


def create_agent_for_root(model_id: str, *, root: str, session_id: str):
    from pydantic_ai import Agent

    agent = Agent(
        model_id,
        system_prompt=(
            "You are a helpful project assistant. You have access to the team's "
            "persistent memory, decisions, lessons, goals, and context from prior "
            "conversations. Use your memory tools proactively to ground your answers "
            "in what the team has recorded. Be specific and cite what you find. "
            "Tool policy: call execute_memory_request first for recall questions; "
            "use search_memory as a secondary check; use trace_memory for explicit "
            "causal trace questions. Do not claim memory is missing unless both "
            "execute and search return no anchors/results."
        ),
        tools=[
            memory_execute_tool(root=root),
            memory_search_tool(root=root),
            memory_trace_tool(root=root),
        ],
    )

    @agent.system_prompt
    def inject_memory():
        return continuity_prompt(root=root, session_id=session_id)

    return agent


async def run_agent_for_root(*, root: str, session_id: str, message: str, model_id: str) -> dict[str, Any]:
    chosen_model = str(model_id or '').strip()
    if not chosen_model:
        raise RuntimeError('no_model_configured')
    agent = create_agent_for_root(chosen_model, root=root, session_id=session_id)
    result = await run_with_memory(
        agent,
        message,
        root=root,
        session_id=session_id,
        turn_id=uuid.uuid4().hex[:12],
        metadata={'source': 'core_memory_demo_benchmark'},
    )
    return {
        'ok': True,
        'model_id': chosen_model,
        'assistant': str(getattr(result, 'output', None) or getattr(result, 'data', None) or result),
    }
