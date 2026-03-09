from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from republic import ToolContext
from telegram import Bot
from telegram.error import BadRequest

from bub.channels.telegram import TelegramSettings
from bub.envelope import content_of, field_of
from bub.skills import discover_skills
from bub.tools import tool
from bub.types import Envelope

if TYPE_CHECKING:
    from bub.builtin.agent import Agent

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
DEFAULT_HEADERS = {"accept": "text/markdown"}
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10


class TelegramMetadata(TypedDict, total=False):
    chat_id: str | int
    message_id: int
    sender_is_bot: bool
    username: str


def _get_agent(context: ToolContext) -> Agent:
    if "_runtime_agent" not in context.state:
        raise RuntimeError("no runtime agent found in tool context")
    return cast("Agent", context.state["_runtime_agent"])


def _runtime_message(context: ToolContext) -> Envelope | None:
    message = context.state.get("_runtime_message")
    return cast("Envelope | None", message)


def _runtime_telegram_metadata(context: ToolContext) -> TelegramMetadata:
    message = _runtime_message(context)
    if message is None or field_of(message, "channel") != "telegram":
        return {}
    raw = content_of(message)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return cast("TelegramMetadata", data) if isinstance(data, dict) else {}


def _mark_channel_response(context: ToolContext, *, final: bool) -> None:
    if final:
        context.state["_channel_response_sent"] = True


def _telegram_bot() -> Bot:
    settings = TelegramSettings()
    if not settings.token:
        raise RuntimeError("BUB_TELEGRAM_TOKEN is required for telegram tools")
    return Bot(token=settings.token)


def _resolve_telegram_chat_id(context: ToolContext, chat_id: str | None) -> str:
    metadata = _runtime_telegram_metadata(context)
    resolved_chat_id = chat_id or (str(metadata["chat_id"]) if "chat_id" in metadata else None)
    if not resolved_chat_id:
        raise RuntimeError("chat_id is required when not running inside a Telegram session")
    return resolved_chat_id


def _telegram_defaults(context: ToolContext) -> tuple[str | None, int | None, str | None]:
    metadata = _runtime_telegram_metadata(context)
    reply_to: int | None = None
    mention_username: str | None = None
    if metadata.get("sender_is_bot"):
        username = metadata.get("username")
        if isinstance(username, str) and username.strip():
            mention_username = username.strip()
    else:
        message_id = metadata.get("message_id")
        if isinstance(message_id, int):
            reply_to = message_id
    resolved_chat_id = str(metadata["chat_id"]) if "chat_id" in metadata else None
    return resolved_chat_id, reply_to, mention_username


def _telegram_result(
    *,
    action: str,
    chat_id: int | str,
    message_id: int,
    final: bool,
) -> dict[str, object]:
    return {
        "ok": True,
        "channel": "telegram",
        "action": action,
        "chat_id": str(chat_id),
        "message_id": message_id,
        "final": final,
    }


@tool(context=True)
async def bash(
    cmd: str, cwd: str | None = None, timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS, *, context: ToolContext
) -> str:
    """Run a shell command and return its output within a time limit. Raises if the command fails or times out."""
    workspace = context.state.get("_runtime_workspace")
    completed = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd or workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(timeout_seconds):
        stdout_bytes, stderr_bytes = await completed.communicate()
    stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace").strip()
    stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        message = stderr_text or stdout_text or f"exit={completed.returncode}"
        raise RuntimeError(f"exit={completed.returncode}: {message}")
    return stdout_text or "(no output)"


@tool(context=True, name="telegram.send")
async def telegram_send(
    message: str,
    chat_id: str | None = None,
    reply_to_message_id: int | None = None,
    mention_username: str | None = None,
    final: bool = True,
    *,
    context: ToolContext,
) -> dict[str, object]:
    """Send a Telegram message. Defaults to replying in the current Telegram chat when available."""
    _, default_reply_to, default_mention = _telegram_defaults(context)
    resolved_chat_id = _resolve_telegram_chat_id(context, chat_id)
    resolved_reply_to = reply_to_message_id if reply_to_message_id is not None else default_reply_to
    resolved_mention = mention_username if mention_username is not None else default_mention
    text = f"@{resolved_mention} {message}" if resolved_mention else message

    bot = _telegram_bot()
    try:
        sent = await bot.send_message(
            chat_id=resolved_chat_id,
            text=text,
            reply_to_message_id=resolved_reply_to,
        )
    except BadRequest:
        if reply_to_message_id is None and resolved_reply_to is not None:
            sent = await bot.send_message(chat_id=resolved_chat_id, text=text)
        else:
            raise

    _mark_channel_response(context, final=final)
    return _telegram_result(action="send", chat_id=sent.chat_id, message_id=sent.message_id, final=final)


@tool(context=True, name="telegram.edit")
async def telegram_edit(
    text: str,
    message_id: int,
    chat_id: str | None = None,
    final: bool = True,
    *,
    context: ToolContext,
) -> dict[str, object]:
    """Edit an existing Telegram message."""
    resolved_chat_id = _resolve_telegram_chat_id(context, chat_id)

    bot = _telegram_bot()
    message_obj = await bot.edit_message_text(chat_id=resolved_chat_id, message_id=message_id, text=text)
    _mark_channel_response(context, final=final)
    return _telegram_result(action="edit", chat_id=message_obj.chat_id, message_id=message_obj.message_id, final=final)


@tool(context=True, name="fs.read")
def fs_read(path: str, offset: int = 0, limit: int | None = None, *, context: ToolContext) -> str:
    """Read a text file and return its content. Supports optional pagination with offset and limit."""
    resolved_path = _resolve_path(context, path)
    text = resolved_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = max(0, min(offset, len(lines)))
    end = len(lines) if limit is None else min(len(lines), start + max(0, limit))
    return "\n".join(lines[start:end])


@tool(context=True, name="fs.write")
def fs_write(path: str, content: str, *, context: ToolContext) -> str:
    """Write content to a text file."""
    resolved_path = _resolve_path(context, path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(content, encoding="utf-8")
    return f"wrote: {resolved_path}"


@tool(context=True, name="fs.edit")
def fs_edit(path: str, old: str, new: str, start: int = 0, *, context: ToolContext) -> str:
    """Edit a text file by replacing old text with new text. You can specify the line number to start searching for the old text."""
    resolved_path = _resolve_path(context, path)
    text = resolved_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    prev, to_replace = "\n".join(lines[:start]), "\n".join(lines[start:])
    if old not in to_replace:
        raise ValueError(f"'{old}' not found in {resolved_path} from line {start}")
    replaced = to_replace.replace(old, new)
    if prev:
        replaced = prev + "\n" + replaced
    resolved_path.write_text(replaced, encoding="utf-8")
    return f"edited: {resolved_path}"


@tool(context=True, name="skill")
def skill_describe(name: str, *, context: ToolContext) -> str:
    """Load the skill content by name. Return the location and skill content."""
    from bub.utils import workspace_from_state

    workspace = workspace_from_state(context.state)
    skill_index = {skill.name: skill for skill in discover_skills(workspace)}
    if name.casefold() not in skill_index:
        return "(no such skill)"
    skill = skill_index[name.casefold()]
    return f"Location: {skill.location}\n---\n{skill.body() or '(no content)'}"


@tool(context=True, name="tape.info")
async def tape_info(context: ToolContext) -> str:
    """Get information about the current tape, such as number of entries and anchors."""
    agent = _get_agent(context)
    info = await agent.tapes.info(context.tape or "")
    return (
        f"name: {info.name}\n"
        f"entries: {info.entries}\n"
        f"anchors: {info.anchors}\n"
        f"last_anchor: {info.last_anchor}\n"
        f"entries_since_last_anchor: {info.entries_since_last_anchor}\n"
        f"last_token_usage: {info.last_token_usage}"
    )


@tool(context=True, name="tape.search")
async def tape_search(query: str, limit: int = 20, *, context: ToolContext) -> str:
    """Search for entries in the current tape that match the query. Returns a list of matching entries."""
    agent = _get_agent(context)
    entries = await agent.tapes.search(context.tape or "", query=query, limit=limit)
    if not entries:
        return "(no matches)"
    return "\n".join(f"- {json.dumps(entry.payload)}" for entry in entries)


@tool(context=True, name="tape.reset")
async def tape_reset(archive: bool = False, *, context: ToolContext) -> str:
    """Reset the current tape, optionally archiving it."""
    agent = _get_agent(context)
    result = await agent.tapes.reset(context.tape or "", archive=archive)
    return result


@tool(context=True, name="tape.handoff")
async def tape_handoff(name: str = "handoff", summary: str = "", *, context: ToolContext) -> str:
    """Add a handoff anchor to the current tape."""
    agent = _get_agent(context)
    await agent.tapes.handoff(context.tape or "", name=name, state={"summary": summary})
    return f"anchor added: {name}"


@tool(context=True, name="tape.anchors")
async def tape_anchors(*, context: ToolContext) -> str:
    """List anchors in the current tape."""
    agent = _get_agent(context)
    anchors = await agent.tapes.anchors(context.tape or "")
    if not anchors:
        return "(no anchors)"
    return "\n".join(f"- {anchor.name}" for anchor in anchors)


@tool(name="web.fetch")
async def web_fetch(url: str, headers: dict | None = None, timeout: int | None = None) -> str:
    """Fetch(GET) the content of a web page, returning markdown if possible."""
    import aiohttp

    headers = {**DEFAULT_HEADERS, **(headers or {})}
    timeout = timeout or DEFAULT_REQUEST_TIMEOUT_SECONDS

    async with (
        aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as session,
        session.get(url) as response,
    ):
        response.raise_for_status()
        return await response.text()


@tool(name="help")
def show_help() -> str:
    """Show a help message."""
    return (
        "Commands use ',' at line start.\n"
        "Known internal commands:\n"
        "  ,help\n"
        "  ,skill name=foo\n"
        "  ,tape.info\n"
        "  ,tape.search query=error\n"
        "  ,tape.handoff name=phase-1 summary='done'\n"
        "  ,tape.anchors\n"
        "  ,fs.read path=README.md\n"
        "  ,fs.write path=tmp.txt content='hello'\n"
        "  ,fs.edit path=tmp.txt old=hello new=world\n"
        "Any unknown command after ',' is executed as shell via bash."
    )


def _resolve_path(context: ToolContext, raw_path: str) -> Path:
    workspace = context.state.get("_runtime_workspace")
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if workspace is None:
        raise ValueError(f"relative path '{raw_path}' is not allowed without a workspace")
    if not isinstance(workspace, str | Path):
        raise TypeError("runtime workspace must be a filesystem path")
    workspace_path = Path(workspace)
    return (workspace_path / path).resolve()
