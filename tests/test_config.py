from newsbot.config import config_path


def test_config_path_defaults_to_root_local_sources(monkeypatch):
    monkeypatch.delenv("SOURCES_PATH", raising=False)

    assert config_path().endswith("sources.local.json")


def test_config_path_honors_sources_path(monkeypatch):
    monkeypatch.setenv("SOURCES_PATH", "custom/sources.json")

    assert config_path() == "custom/sources.json"
