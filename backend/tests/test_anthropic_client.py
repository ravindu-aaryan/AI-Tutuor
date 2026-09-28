"""The Claude adapter builds the right request and handles stop reasons (HTTP is mocked)."""

import json

import anthropic
import httpx2
import pytest

from app.llm import LLMError
from app.llm.anthropic_client import FALLBACK_BETA, AnthropicLLM
from app.tutor.prompts import AnswerEvaluation

GOOD = {"verdict": "correct", "score": 1.0, "feedback": "Yes!", "misconception": None}


def make(stop_reason="end_turn", payload=GOOD, status=200, fallbacks="default"):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["headers"] = dict(req.headers)
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 4},
        })

    client = anthropic.Anthropic(api_key="test", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return AnthropicLLM(model="claude-opus-5", effort="low", fallbacks=fallbacks, client=client), seen


def test_structured_request_and_parse():
    llm, seen = make()
    out = llm.generate(system="sys", prompt="grade this", schema=AnswerEvaluation, purpose="evaluate")
    assert out.verdict == "correct"
    body = seen["body"]
    assert body["model"] == "claude-opus-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in seen["headers"]["anthropic-beta"]


def test_fallbacks_can_be_disabled():
    llm, seen = make(fallbacks="off")
    llm.generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")
    assert "fallbacks" not in seen["body"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reasons_raise(stop):
    llm, _ = make(stop_reason=stop)
    with pytest.raises(LLMError):
        llm.generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")


def test_api_errors_become_llm_errors():
    llm, _ = make(status=500)
    with pytest.raises(LLMError):
        llm.generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")
