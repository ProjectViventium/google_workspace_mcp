from __future__ import annotations

import pytest

import gmail.gmail_tools  # noqa: F401 - import registers the Gmail tools
from core.server import server


@pytest.mark.asyncio
async def test_gmail_tools_declare_read_and_write_effects_for_broker_policy():
    tools = await server.get_tools()

    for name in {
        "search_gmail_messages",
        "get_gmail_message_content",
        "get_gmail_messages_content_batch",
        "get_gmail_thread_content",
        "get_gmail_threads_content_batch",
        "list_gmail_labels",
    }:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False

    for name in {
        "send_gmail_message",
        "draft_gmail_message",
        "manage_gmail_label",
        "modify_gmail_message_labels",
        "batch_modify_gmail_message_labels",
    }:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is False

    assert tools["send_gmail_message"].annotations.destructiveHint is True
    assert tools["draft_gmail_message"].annotations.destructiveHint is False
    assert tools["start_google_auth"].annotations is not None
    assert tools["start_google_auth"].annotations.readOnlyHint is False
