"""Shared constants and types for agent nodes."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

MAX_ITERATIONS = 10
# The ReAct loop has a step cap, but a provider may still return an arbitrary
# number of calls in a single step. Bound both fan-out and the whole-turn work
# budget so one completion cannot create an unbounded execution chain.
MAX_TOOL_CALLS_PER_TURN = 12
MAX_CONCURRENT_TOOL_CALLS_PER_STEP = 4
MAX_SEARCH_KB_CALLS_PER_STEP = 3
MAX_TOOL_RESULT_TOKENS_PER_CALL = 1_500
MAX_TOOL_RESULT_TOKENS_PER_STEP = 4_500
MAX_KB_REWRITE_QUERIES = 3
MAX_AUTO_CONTINUATIONS = 2
EMPTY_ANSWER_FALLBACK = (
    "本轮模型未返回有效内容。请直接点重试，或换一种问法后再试一次。"
)

_TRUSTED_CONTEXT_SOURCES = {"profile", "memory", "summary"}
_QUERY_POLICY_ACTIONS = {"direct", "normalize", "expand", "skip_kb"}
_QUERY_POLICY_MODES = {"always_direct", "rule_only", "llm_fallback", "always_llm"}
_RULE_SKIP_KEYWORDS = (
    "你好",
    "您好",
    "谢谢",
    "多谢",
    "你是谁",
    "总结刚才",
    "总结上一轮",
    "刚才的回答",
    "上一轮回答",
    "复制",
    "导出",
    "分享",
    "翻译成",
    "润色",
    "改写这段",
)
_RULE_ABUSE_HINTS = (
    "去死",
    "滚开",
    "滚蛋",
    "傻逼",
    "垃圾",
)
_RULE_INFORMATION_SEEKING_HINTS = (
    "?",
    "？",
    "吗",
    "么",
    "如何",
    "怎么",
    "为什么",
    "多少",
    "哪些",
    "是否",
    "能否",
    "能不能",
)
_RULE_MULTI_INTENT_KEYWORDS = (
    "以及",
    "同时",
    "分别",
    "对比",
    "区别",
    "差异",
    "是否",
    "哪些",
    "如何",
    "怎么",
    "安全",
    "本地",
    "部署",
    "私有化",
    "权限",
    "加密",
    "隐私",
    "合规",
)
_RULE_FOLLOWUP_KEYWORDS = (
    "这个",
    "那个",
    "它",
    "该功能",
    "上面",
    "刚才",
    "前面",
    "这种",
)

_KG_NEED_HINTS = (
    "关系",
    "关联",
    "依赖",
    "引用",
    "链路",
    "图谱",
    "谁连接",
    "如何连接",
    "之间的",
    "related",
    "relationship",
    "depends",
    "depends on",
    "connected to",
)


QueryPolicyAction = Literal["direct", "normalize", "expand", "skip_kb"]
QueryPolicySource = Literal["rule", "llm", "fallback"]


class QueryPolicyDecision(TypedDict):
    action: QueryPolicyAction
    queries: list[dict[str, Any]]
    reason: str
    source: QueryPolicySource
    latency_ms: int


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the latest real user utterance, skipping synthetic tool-result turns."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
            continue
        if isinstance(content, list):
            # Tool-result user turns are structured lists without text blocks;
            # skip them so rewrite/reasoning still sees the original question.
            text = "\n".join(
                str(block.get("text", "")).strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""
