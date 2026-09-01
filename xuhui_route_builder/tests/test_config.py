from pathlib import Path

import pytest

from xuhui_route_builder.config import Settings, load_settings


def test_load_settings_reads_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AMAP_WEB_SERVICE_KEY=test-web-key\nBAIDU_MAP_AK=test-baidu-ak\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file)

    assert settings.amap_web_service_key == "test-web-key"
    assert settings.baidu_map_ak == "test-baidu-ak"
    assert settings.raw_dir.name == "raw"


def test_load_settings_reads_utf8_bom_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AMAP_WEB_SERVICE_KEY=test-web-key\n", encoding="utf-8-sig")

    settings = load_settings(env_file)

    assert settings.amap_web_service_key == "test-web-key"


def test_settings_requires_web_service_key() -> None:
    with pytest.raises(ValueError, match="AMAP_WEB_SERVICE_KEY"):
        Settings(amap_web_service_key="")
