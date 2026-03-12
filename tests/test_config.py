from zepp_life_mcp.config import Config, load_config, save_config


def test_config_roundtrip(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("zepp_life_mcp.config.get_config_path", lambda: config_file)

    config = Config(mode="cloud_session", region="eu")
    save_config(config)
    loaded = load_config()

    assert loaded.mode == "cloud_session"
    assert loaded.region == "eu"
    assert loaded.database_path.name == "zepp_life.db"
