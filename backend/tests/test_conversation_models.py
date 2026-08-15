from datetime import datetime, timedelta, timezone

from src.conversations.models import Conversation, Message


def test_conversation_timestamps_are_serialized_as_explicit_utc() -> None:
    naive_utc = datetime(2026, 8, 14, 7, 22)
    conversation = Conversation(
        id="conversation-1",
        user_id="user-1",
        created_at=naive_utc,
        updated_at=naive_utc,
        finalized_at=naive_utc + timedelta(minutes=1),
    )

    assert conversation.to_summary_dict() == {
        "id": "conversation-1",
        "title": "新对话",
        "kb_id": None,
        "llm_model": None,
        "message_count": 0,
        "created_at": "2026-08-14T07:22:00+00:00",
        "updated_at": "2026-08-14T07:22:00+00:00",
        "finalized_at": "2026-08-14T07:23:00+00:00",
    }


def test_message_timestamp_is_serialized_as_explicit_utc() -> None:
    message = Message(
        id="message-1",
        conversation_id="conversation-1",
        role="user",
        content="你好",
        created_at=datetime(2026, 8, 14, 15, 22, tzinfo=timezone(timedelta(hours=8))),
    )

    assert message.to_public_dict()["created_at"] == "2026-08-14T07:22:00+00:00"


def test_message_round_trips_interleaved_tool_timeline() -> None:
    parts = [
        {"type": "text", "text": "先检索。"},
        {"type": "tools", "tools": [{"id": "tool-1", "name": "search_kb", "status": "ok"}]},
        {"type": "text", "text": "再回答。"},
    ]
    message = Message(
        id="message-2",
        conversation_id="conversation-1",
        role="assistant",
        content="先检索。\n\n再回答。",
        tool_call_log=Message.encode_tool_call_log(
            [{"id": "tool-1", "name": "search_kb", "status": "ok"}], parts
        ),
    )

    public = message.to_public_dict()
    assert public["parts"] == parts
    assert public["tools"] == [{"id": "tool-1", "name": "search_kb", "status": "ok"}]
