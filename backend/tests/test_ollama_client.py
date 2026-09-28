"""The local-model adapter (Ollama HTTP is mocked)."""

import json

import httpx
import pytest

from app.llm import LLMError
from app.llm.ollama_client import OllamaLLM, ollama_status
from app.tutor.prompts import AnswerEvaluation

GOOD = json.dumps({"verdict": "partial", "score": 0.5, "feedback": "Nearly", "misconception": None})


def fake_post(replies, seen):
    def post(url, json=None, timeout=None):  # noqa: A002 - mirrors httpx
        seen.append((url, json))
        status, content = replies.pop(0)
        return httpx.Response(status, json={"message": {"content": content}, "eval_count": 5}, request=httpx.Request("POST", url))

    return post


def test_request_and_parse(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "post", fake_post([(200, GOOD)], seen))
    out = OllamaLLM(base_url="http://box:11434/", model="qwen2.5:7b").generate(
        system="sys", prompt="p", schema=AnswerEvaluation, purpose="evaluate"
    )
    assert out.verdict == "partial"
    url, body = seen[0]
    assert url == "http://box:11434/api/chat"
    assert body["model"] == "qwen2.5:7b" and body["stream"] is False
    assert body["format"]["properties"]["verdict"]["enum"] == ["correct", "partial", "incorrect"]
    assert body["messages"][0]["role"] == "system"


def test_invalid_json_is_retried_once(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "post", fake_post([(200, "{not json"), (200, GOOD)], seen))
    assert OllamaLLM(base_url="http://x", model="m").generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")
    assert len(seen) == 2
    monkeypatch.setattr(httpx, "post", fake_post([(200, "{"), (200, "{")], []))
    with pytest.raises(LLMError, match="couldn't be understood"):
        OllamaLLM(base_url="http://x", model="m").generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")


def test_missing_model_and_no_server(monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post([(404, "")], []))
    with pytest.raises(LLMError, match="ollama pull m"):
        OllamaLLM(base_url="http://x", model="m").generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")

    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(LLMError, match="Is Ollama installed"):
        OllamaLLM(base_url="http://x", model="m").generate(system="s", prompt="p", schema=AnswerEvaluation, purpose="x")


def test_status(monkeypatch):
    def tags(url, timeout=None):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", tags)
    assert ollama_status("http://x", "qwen2.5:7b")[0]
    ok, detail = ollama_status("http://x", "llama3.2:3b")
    assert not ok and "ollama pull llama3.2:3b" in detail
