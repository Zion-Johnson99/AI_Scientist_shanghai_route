from __future__ import annotations

from qwen_harness.llm.client import QwenModelClient


def _client(default_effort: str) -> QwenModelClient:
    client = object.__new__(QwenModelClient)
    client.default_reasoning_effort = default_effort
    client.stage_reasoning_effort = {}
    return client


def test_reasoning_effort_enables_thinking_for_bailian_contract() -> None:
    assert _client("medium")._extra_body("problem_framing") == {
        "enable_thinking": True,
        "reasoning_effort": "medium",
        "preserve_thinking": False,
    }


def test_none_reasoning_effort_keeps_thinking_disabled() -> None:
    assert _client("none")._extra_body("problem_framing") == {
        "enable_thinking": False,
        "reasoning_effort": "none",
        "preserve_thinking": False,
    }
