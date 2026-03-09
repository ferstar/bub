from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from republic import ToolContext
from telegram.error import BadRequest

from bub.builtin.tools import telegram_edit, telegram_send
from bub.channels.message import ChannelMessage

TEST_WORKSPACE = "/workspace"
TEST_SESSION_ID = "telegram:10001"
TEST_CHAT_ID = "10001"
TEST_MESSAGE_ID = 600
TEST_USERNAME = "test-user"
TEST_BOT_USERNAME = "assistant-bot"


@dataclass
class FakeTelegramMessage:
    chat_id: int
    message_id: int


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_first_reply = False

    async def send_message(self, **kwargs):
        self.calls.append(("send", kwargs))
        if self.fail_first_reply and kwargs.get("reply_to_message_id") is not None:
            self.fail_first_reply = False
            raise BadRequest("reply target not found")
        return FakeTelegramMessage(chat_id=int(str(kwargs["chat_id"])), message_id=601)

    async def edit_message_text(self, **kwargs):
        self.calls.append(("edit", kwargs))
        return FakeTelegramMessage(chat_id=int(str(kwargs["chat_id"])), message_id=int(kwargs["message_id"]))


def _telegram_payload(*, sender_is_bot: bool = False, username: str = TEST_USERNAME) -> str:
    return json.dumps(
        {
            "message": "hi",
            "chat_id": TEST_CHAT_ID,
            "message_id": TEST_MESSAGE_ID,
            "sender_is_bot": sender_is_bot,
            "username": username,
        }
    )


def _telegram_context(content: str, workspace: str = TEST_WORKSPACE) -> ToolContext:
    return ToolContext(
        tape=None,
        run_id="test",
        state={
            "_runtime_workspace": workspace,
            "_runtime_message": ChannelMessage(
                session_id=TEST_SESSION_ID,
                channel="telegram",
                chat_id=TEST_CHAT_ID,
                content=content,
            ),
        },
    )


@pytest.mark.asyncio
async def test_telegram_send_uses_runtime_defaults_and_marks_final(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _telegram_context(_telegram_payload())
    bot = FakeBot()
    monkeypatch.setattr("bub.builtin.tools._telegram_bot", lambda: bot)

    result = await telegram_send.run("done", context=context)

    assert result["ok"] is True
    assert result["final"] is True
    assert context.state["_channel_response_sent"] is True
    assert bot.calls == [
        (
            "send",
            {
                "chat_id": TEST_CHAT_ID,
                "text": "done",
                "reply_to_message_id": TEST_MESSAGE_ID,
            },
        )
    ]


@pytest.mark.asyncio
async def test_telegram_send_progress_does_not_mark_final(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _telegram_context(_telegram_payload())
    bot = FakeBot()
    monkeypatch.setattr("bub.builtin.tools._telegram_bot", lambda: bot)

    result = await telegram_send.run("working", final=False, context=context)

    assert result["final"] is False
    assert "_channel_response_sent" not in context.state


@pytest.mark.asyncio
async def test_telegram_send_retries_without_reply_for_implicit_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _telegram_context(_telegram_payload())
    bot = FakeBot()
    bot.fail_first_reply = True
    monkeypatch.setattr("bub.builtin.tools._telegram_bot", lambda: bot)

    await telegram_send.run("done", context=context)

    assert bot.calls == [
        ("send", {"chat_id": TEST_CHAT_ID, "text": "done", "reply_to_message_id": TEST_MESSAGE_ID}),
        ("send", {"chat_id": TEST_CHAT_ID, "text": "done"}),
    ]


@pytest.mark.asyncio
async def test_telegram_send_mentions_bot_sender_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _telegram_context(_telegram_payload(sender_is_bot=True, username=TEST_BOT_USERNAME))
    bot = FakeBot()
    monkeypatch.setattr("bub.builtin.tools._telegram_bot", lambda: bot)

    await telegram_send.run("done", context=context)

    assert bot.calls == [
        (
            "send",
            {
                "chat_id": TEST_CHAT_ID,
                "text": f"@{TEST_BOT_USERNAME} done",
                "reply_to_message_id": None,
            },
        )
    ]


@pytest.mark.asyncio
async def test_telegram_edit_marks_final(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _telegram_context(_telegram_payload())
    bot = FakeBot()
    monkeypatch.setattr("bub.builtin.tools._telegram_bot", lambda: bot)

    result = await telegram_edit.run("done", message_id=601, context=context)

    assert result["ok"] is True
    assert context.state["_channel_response_sent"] is True
    assert bot.calls == [
        (
            "edit",
            {
                "chat_id": TEST_CHAT_ID,
                "message_id": 601,
                "text": "done",
            },
        )
    ]
