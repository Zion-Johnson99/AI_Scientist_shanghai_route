from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    amap_web_service_key: str = Field(default="")
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    interim_dir: Path = PROJECT_ROOT / "data" / "interim"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    web_data_dir: Path = PROJECT_ROOT / "data" / "web"
    seed_dir: Path = PROJECT_ROOT / "data" / "seeds"

    @field_validator("amap_web_service_key")
    @classmethod
    def require_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("AMAP_WEB_SERVICE_KEY is required")
        return value.strip()


def load_settings(env_file: Path | None = None) -> Settings:
    env_path = env_file or PROJECT_ROOT / ".env"
    values = dotenv_values(env_path, encoding="utf-8-sig") if env_path.exists() else {}
    return Settings(amap_web_service_key=str(values.get("AMAP_WEB_SERVICE_KEY", "")))
