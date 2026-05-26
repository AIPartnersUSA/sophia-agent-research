"""
Placeholder test until AWS STT/LLM/TTS endpoints are wired.

Once plugins are in place, mirror my-agent/tests/test_agent.py structure
(judge LLM + AgentSession + result.expect chain).
"""

import pytest

from agent import Assistant


@pytest.mark.asyncio
async def test_assistant_constructs():
    """Smoke test: the Assistant class can be instantiated."""
    assistant = Assistant()
    assert assistant is not None
