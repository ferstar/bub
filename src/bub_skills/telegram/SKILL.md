---
name: telegram
description: |
  Telegram Bot skill for sending and editing Telegram messages via Bot API.
  Use when Bub needs to: (1) Send a message to a Telegram user/group/channel,
  (2) Reply to a specific Telegram message with reply_to_message_id,
  (3) Edit an existing Telegram message, or (4) Push proactive Telegram notifications
  when working outside an active Telegram session.
metadata:
  channel: telegram
---

# Telegram Skill

Agent-facing execution guide for Telegram outbound communication.

Assumption: `BUB_TELEGRAM_TOKEN` is already available.

## Required Inputs

Collect these before execution:

- `chat_id` (required)
- `message_id` (required for edit or reply when source is not a bot)
- message content (required for send/edit)
- `reply_to_message_id` (required for threaded reply behavior)

## Execution Policy

1. Prefer the built-in tools `telegram_send` and `telegram_edit` over shell commands.
2. Do not use `bash`, `curl`, or the fallback scripts for normal Telegram sends when these tools are available.
3. If handling a direct user message in Telegram and `message_id` is known, `telegram_send` will reply to that message by default.
4. If source metadata says sender is a bot (`sender_is_bot=true`), `telegram_send` will avoid reply mode and prefix with `@<sender_username>` by default.
5. For long-running tasks, send progress with `final=false`, then send or edit the final user-visible response with `final=true`.
6. Avoid emitting HTML tags in message content.

## Active Response Policy

When this skill is in scope, prefer proactive and timely Telegram updates:

- Send an immediate acknowledgment for newly assigned tasks
- Send progress updates for long-running operations using message edits
- Send completion notifications when work finishes
- Send important status or failure notifications without waiting for follow-up prompts
- If execution is blocked or fails, send a problem report immediately with cause, impact, and next action

Recommended pattern:

1. Send a short acknowledgment reply
2. Continue processing
3. If blocked, edit or send an issue update immediately
4. Edit the acknowledgment message with final result when possible

## Voice Message Policy

When the inbound Telegram message is voice:

1. Transcribe the voice input first (use STT skill if available)
2. Prepare response content based on transcription
3. Prefer voice response output (use TTS skill if available)
4. If voice output is unavailable, send a concise text fallback and state limitation

## Reaction Policy

When an inbound Telegram message warrants acknowledgment but does not merit a full reply, use a Telegram reaction as the response.
But when any explanation or details are needed, use a normal reply instead.

## Preferred Tool Calls

- `telegram_send(message="...", final=True)`
- `telegram_send(message="working...", final=False)`
- `telegram_edit(text="done", message_id=123, final=True)`

Use explicit `chat_id` when sending outside the current Telegram session.

## Shell Fallback

Paths are relative to this skill directory.

```bash
# Send message
uv run ./scripts/telegram_send.py \
  --chat-id <CHAT_ID> \
  --message "<TEXT>"

# Send multi-line message (heredoc)
uv run ./scripts/telegram_send.py \
  --chat-id <CHAT_ID> \
  --message "$(cat <<'EOF'
Build finished successfully.
Summary:
- 12 tests passed
- 0 failures
EOF
)"

# Send reply to a specific message
uv run ./scripts/telegram_send.py \
  --chat-id <CHAT_ID> \
  --message "<TEXT>" \
  --reply-to <MESSAGE_ID>

# Source message sender is bot: no direct reply, use @user_id style
uv run ./scripts/telegram_send.py \
  --chat-id <CHAT_ID> \
  --message "<TEXT>" \
  --source-is-bot \
  --source-username <USERNAME>

# Edit existing message
uv run ./scripts/telegram_edit.py \
  --chat-id <CHAT_ID> \
  --message-id <MESSAGE_ID> \
  --text "<TEXT>"
```

For other actions that not covered by these scripts, use `curl` to call Telegram Bot API directly with the provided token.

## Script Interface Reference

### `telegram_send.py`

- `--chat-id`, `-c`: required, supports comma-separated ids
- `--message`, `-m`: required
- `--reply-to`, `-r`: optional
- `--token`, `-t`: optional (normally not needed)
- `--source-is-bot`: optional flag, disables reply mode and switches to `@user_id` style
- `--source-user-id`: optional, required when `--source-is-bot` is set

### `telegram_edit.py`

- `--chat-id`, `-c`: required
- `--message-id`, `-m`: required
- `--text`, `-t`: required
- `--token`: optional (normally not needed)
