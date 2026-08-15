from types import SimpleNamespace as NS

from newsbot import llm


def test_get_client_configures_timeout_and_retries(monkeypatch):
    calls = []

    def fake_openai(**kwargs):
        calls.append(kwargs)
        return NS()

    llm.get_client.cache_clear()
    monkeypatch.setattr(llm, "OpenAI", fake_openai)

    assert llm.get_client() is not None
    assert calls == [{
        "timeout": llm.OPENAI_TIMEOUT_SECONDS,
        "max_retries": llm.OPENAI_MAX_RETRIES,
    }]

    llm.get_client.cache_clear()
