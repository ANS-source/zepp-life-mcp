"""Configuration management for Zepp Life MCP."""

import json
from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir, user_data_dir, user_log_dir
from pydantic import BaseModel, ConfigDict, Field


def _default_database_path() -> Path:
    return Path(user_data_dir("zepp-life-mcp")) / "zepp_life.db"


def _default_logs_path() -> Path:
    return Path(user_log_dir("zepp-life-mcp")) / "zepp_life.log"


class Config(BaseModel):
    mode: Literal["export_file", "cloud_session", "not_configured"] = "not_configured"
    region: str = "eu"
    timezone: str = Field(default="UTC")
    database_path: Path = Field(default_factory=_default_database_path)
    logs_path: Path = Field(default_factory=_default_logs_path)
    export_path: Path | None = None
    auto_sync_on_start: bool = True
    stale_after_minutes: int = 60
    store_raw_payloads: bool = True
    default_lookback_days: int = 30

    model_config = ConfigDict(arbitrary_types_allowed=True)


def get_config_dir() -> Path:
    config_dir = Path(user_config_dir("zepp-life-mcp"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def load_config() -> Config:
    config_path = get_config_path()
    if not config_path.exists():
        config = Config()
        save_config(config)
        return config

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    if "database_path" in data and isinstance(data["database_path"], str):
        data["database_path"] = Path(data["database_path"])
    if "logs_path" in data and isinstance(data["logs_path"], str):
        data["logs_path"] = Path(data["logs_path"])
    if "export_path" in data and isinstance(data["export_path"], str):
        data["export_path"] = Path(data["export_path"]) if data["export_path"] else None

    return Config(**data)


def save_config(config: Config) -> None:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump()
    data["database_path"] = str(data["database_path"])
    data["logs_path"] = str(data["logs_path"])
    data["export_path"] = str(data["export_path"]) if data["export_path"] else None

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
