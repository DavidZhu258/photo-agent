import importlib


def test_newapi_env_takes_priority_for_travel_main_channel(monkeypatch):
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-token")
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://www.zzshu.cc/v1")
    monkeypatch.setenv("TRAVEL_MAIN_API_KEY", "old-travel-token")
    monkeypatch.setenv("TRAVEL_MAIN_BASE_URL", "https://old.example/v1")
    monkeypatch.setenv("ZZSHU_API_KEY", "old-zzshu-token")
    monkeypatch.setenv("ZZSHU_BASE_URL", "https://zzshu.cc/v1")

    import app.config as config

    reloaded = importlib.reload(config)
    try:
        assert reloaded.settings.travel_main_api_key == "newapi-token"
        assert reloaded.settings.travel_main_base_url == "https://www.zzshu.cc/v1"
    finally:
        importlib.reload(config)
