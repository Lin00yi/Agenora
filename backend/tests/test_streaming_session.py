from __future__ import annotations

from src.api.streaming.session import _human_interrupt_content


def test_human_interrupt_persists_its_prompt_as_assistant_content() -> None:
    assert _human_interrupt_content({"prompt": "请选择要退款的订单。"}) == "请选择要退款的订单。"
    assert _human_interrupt_content({"prompt": "   "}) == "请补充继续处理所需的信息。"
