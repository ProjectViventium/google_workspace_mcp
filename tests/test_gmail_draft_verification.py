from __future__ import annotations

from email.header import Header

import pytest

from gmail.gmail_tools import draft_gmail_message


class _Call:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _Drafts:
    def __init__(self, persisted=None, get_error: Exception | None = None):
        self.persisted = persisted
        self.get_error = get_error
        self.create_body = None
        self.get_args = None

    def create(self, *, userId, body):
        self.create_body = body
        return _Call({"id": "draft-1", "message": {"id": "message-1"}})

    def get(self, **kwargs):
        self.get_args = kwargs
        return _Call(self.persisted, self.get_error)


class _Users:
    def __init__(self, drafts: _Drafts):
        self._drafts = drafts

    def drafts(self):
        return self._drafts


class _GmailService:
    def __init__(self, drafts: _Drafts):
        self._users = _Users(drafts)

    def users(self):
        return self._users


def _raw_draft_tool():
    return draft_gmail_message.fn.__wrapped__.__wrapped__


@pytest.mark.asyncio
async def test_draft_result_verifies_persisted_reply_headers_and_unsent_state():
    drafts = _Drafts(
        persisted={
            "id": "draft-1",
            "message": {
                "id": "message-1",
                "threadId": "thread-1",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Re: Example thread"},
                        {"name": "To", "value": "recipient@example.com"},
                    ]
                },
            },
        }
    )

    result = await _raw_draft_tool()(
        _GmailService(drafts),
        "owner@example.com",
        subject="Re: Example thread",
        body="Synthetic reply body",
        to="recipient@example.com",
        cc=None,
        bcc=None,
        thread_id="thread-1",
        in_reply_to=None,
        references=None,
    )

    assert drafts.get_args == {
        "userId": "me",
        "id": "draft-1",
        "format": "metadata",
    }
    assert "Draft created and verified unsent." in result
    assert "Subject: Re: Example thread" in result
    assert "To: recipient@example.com" in result
    assert "Thread ID: thread-1" in result
    assert "Message ID: message-1" in result


@pytest.mark.asyncio
async def test_draft_result_verifies_the_composed_reply_subject():
    drafts = _Drafts(
        persisted={
            "id": "draft-1",
            "message": {
                "id": "message-1",
                "threadId": "thread-1",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Re: Example thread"},
                        {"name": "To", "value": "recipient@example.com"},
                    ]
                },
            },
        }
    )

    result = await _raw_draft_tool()(
        _GmailService(drafts),
        "owner@example.com",
        subject="Example thread",
        body="Synthetic reply body",
        to="recipient@example.com",
        cc=None,
        bcc=None,
        thread_id="thread-1",
        in_reply_to="<message-1@example.com>",
        references=None,
    )

    assert "Draft created and verified unsent." in result
    assert "Subject: Re: Example thread" in result


@pytest.mark.asyncio
async def test_draft_result_preserves_created_identity_when_verification_is_unavailable():
    drafts = _Drafts(get_error=RuntimeError("synthetic lookup failure"))

    result = await _raw_draft_tool()(
        _GmailService(drafts),
        "owner@example.com",
        subject="Example",
        body="Synthetic body",
        to=None,
        cc=None,
        bcc=None,
        thread_id=None,
        in_reply_to=None,
        references=None,
    )

    assert "Draft created; verification unavailable." in result
    assert "Draft ID: draft-1" in result
    assert "Do not create a replacement draft automatically." in result
    assert "synthetic lookup failure" not in result


@pytest.mark.asyncio
async def test_draft_verification_decodes_rfc2047_subject_and_recipient_headers():
    subject = "Café planning — next steps"
    recipient = "Zoë Example <zoe@example.com>"
    drafts = _Drafts(
        persisted={
            "id": "draft-1",
            "message": {
                "id": "message-1",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": Header(subject, "utf-8").encode()},
                        {"name": "To", "value": Header(recipient, "utf-8").encode()},
                    ]
                },
            },
        }
    )

    result = await _raw_draft_tool()(
        _GmailService(drafts),
        "owner@example.com",
        subject=subject,
        body="Synthetic body",
        to=recipient,
        cc=None,
        bcc=None,
        thread_id=None,
        in_reply_to=None,
        references=None,
    )

    assert "Draft created and verified unsent." in result
    assert f"Subject: {subject}" in result
    assert f"To: {recipient}" in result


@pytest.mark.asyncio
async def test_draft_verification_preserves_trailing_header_whitespace():
    subject = "Example subject "
    drafts = _Drafts(
        persisted={
            "id": "draft-1",
            "message": {
                "id": "message-1",
                "labelIds": ["DRAFT"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": subject},
                    ]
                },
            },
        }
    )

    result = await _raw_draft_tool()(
        _GmailService(drafts),
        "owner@example.com",
        subject=subject,
        body="Synthetic body",
        to=None,
        cc=None,
        bcc=None,
        thread_id=None,
        in_reply_to=None,
        references=None,
    )

    assert "Draft created and verified unsent." in result
