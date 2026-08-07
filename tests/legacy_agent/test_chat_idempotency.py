"""Chat 幂等（P0）：同一 client_message_id 只执行一次，stream 中断 fallback 不产生重复执行。"""

from __future__ import annotations

from ultrafast_memory.chat.schemas import ChatRequest
from ultrafast_memory.chat.service import handle_chat
from ultrafast_memory.chat.session_store import list_messages
from ultrafast_memory.db.init_db import init_database


def _request(session_id: str | None, message: str, client_message_id: str | None) -> ChatRequest:
    return ChatRequest(
        session_id=session_id,
        message=message,
        mode="agent",
        stream=False,
        client_message_id=client_message_id,
    )


def test_idempotent_same_client_message_id(memory_root) -> None:
    init_database()
    first = handle_chat(_request(None, "帮我确认材料", "M-0001"))
    session_id = first.session_id
    messages_after_first = len(list_messages(session_id))

    second = handle_chat(_request(session_id, "帮我确认材料", "M-0001"))
    assert second.assistant_message == first.assistant_message
    assert second.current_stage_code == "idempotent_hit"
    assert any(item.get("step") == "idempotent_hit" for item in second.execution_trace)
    # 幂等命中不追加新消息（user 与 assistant 均不重复）
    assert len(list_messages(session_id)) == messages_after_first


def test_distinct_client_message_id_executes_again(memory_root) -> None:
    init_database()
    first = handle_chat(_request(None, "帮我确认材料", "M-0002"))
    session_id = first.session_id
    messages_after_first = len(list_messages(session_id))

    second = handle_chat(_request(session_id, "帮我确认材料", "M-0003"))
    assert second.current_stage_code != "idempotent_hit"
    assert len(list_messages(session_id)) > messages_after_first


def test_no_client_message_id_not_idempotent(memory_root) -> None:
    init_database()
    first = handle_chat(_request(None, "帮我确认材料", None))
    session_id = first.session_id
    messages_after_first = len(list_messages(session_id))
    second = handle_chat(_request(session_id, "帮我确认材料", None))
    assert second.current_stage_code != "idempotent_hit"
    assert len(list_messages(session_id)) > messages_after_first
