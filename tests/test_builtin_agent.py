from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from bub.builtin.agent import Agent
from bub.framework import BubFramework

TEST_WORKSPACE = "/workspace"


class FakeTape:
    def __init__(self, state: dict[str, object]) -> None:
        self.name = "telegram:room"
        self.context = SimpleNamespace(state=state)


class FakeTapes:
    def __init__(self, tape: FakeTape) -> None:
        self._tape = tape
        self.bootstrap_calls: list[str] = []

    def session_tape(self, session_id: str, workspace) -> FakeTape:
        return self._tape

    @asynccontextmanager
    async def fork_tape(self, name: str):
        yield

    async def ensure_bootstrap_anchor(self, name: str) -> None:
        self.bootstrap_calls.append(name)


@pytest.mark.asyncio
async def test_run_clears_transient_channel_response_flag_between_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = Agent(BubFramework())
    tape = FakeTape({"persisted": "value", "_channel_response_sent": True})
    tapes = FakeTapes(tape)
    agent.__dict__["tapes"] = tapes

    async def fake_agent_loop(*, tape: FakeTape, prompt: str) -> str:
        assert prompt == "hello"
        assert tape.context.state["persisted"] == "value"
        assert tape.context.state["context"] == "ctx"
        assert "_channel_response_sent" not in tape.context.state
        tape.context.state["_channel_response_sent"] = True
        return ""

    monkeypatch.setattr(agent, "_agent_loop", fake_agent_loop)

    result = await agent.run(
        session_id="telegram:room",
        prompt="hello",
        state={"_runtime_workspace": TEST_WORKSPACE, "context": "ctx"},
    )

    assert result == ""
    assert tapes.bootstrap_calls == ["telegram:room"]
    assert tape.context.state == {
        "persisted": "value",
        "_runtime_workspace": TEST_WORKSPACE,
        "context": "ctx",
    }
