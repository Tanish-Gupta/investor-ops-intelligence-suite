from config.settings import Settings


def test_defaults_match_architecture(monkeypatch):
    for key in ("ADAPTER_MODE", "MCP_SERVER_TARGET", "TIMEZONE", "PULSE_MAX_WORDS"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.adapter_mode == "mock"
    assert s.mcp_server_target == "inprocess"
    assert s.pulse_max_words == 250
    assert s.pulse_action_ideas == 3
    assert s.tz.key == "Asia/Kolkata"
    assert s.llm_judge != s.llm_primary  # judge must differ from generator (evals.md)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ADAPTER_MODE", "google")
    monkeypatch.setenv("TOP_K", "7")
    s = Settings(_env_file=None)
    assert s.adapter_mode == "google"
    assert s.top_k == 7


def test_secrets_are_not_printed(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_value")
    s = Settings(_env_file=None)
    assert "gsk_test_value" not in repr(s)
