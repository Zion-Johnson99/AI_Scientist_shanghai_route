from pathlib import Path

import pytest

from xuhui_route_builder.web_map_config import (
    WebMapConfigError,
    generate_web_map_config,
    generate_web_map_config_from_environment,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_generate_web_map_config_writes_only_browser_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    web_root = tmp_path / "web"
    env_file.write_text(
        "\n".join(
            (
                "AMAP_WEB_SERVICE_KEY=server-amap-secret",
                "AMAP_JS_API_KEY=browser-amap-key",
                "AMAP_JS_SECURITY_CODE=browser-amap-security",
                "BAIDU_MAP_AK=server-baidu-secret",
                "TENCENT_SEARCH_KEY=browser-tencent-key",
            )
        ),
        encoding="utf-8",
    )

    amap_target, tencent_target = generate_web_map_config(env_file, web_root)

    amap_content = amap_target.read_text(encoding="utf-8")
    tencent_content = tencent_target.read_text(encoding="utf-8")
    assert 'window.XUHUI_AMAP_JS_KEY = "browser-amap-key";' in amap_content
    assert (
        'window.XUHUI_AMAP_JS_SECURITY_CODE = "browser-amap-security";' in amap_content
    )
    assert 'window.XUHUI_TENCENT_SEARCH_KEY = "browser-tencent-key";' in tencent_content
    assert "server-amap-secret" not in amap_content + tencent_content
    assert "server-baidu-secret" not in amap_content + tencent_content


def test_generate_web_map_config_reports_missing_browser_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AMAP_JS_API_KEY=browser-amap-key\n"
        "AMAP_JS_SECURITY_CODE=browser-amap-security\n",
        encoding="utf-8",
    )

    with pytest.raises(WebMapConfigError, match="TENCENT_SEARCH_KEY 未配置"):
        generate_web_map_config(env_file, tmp_path / "web")


def test_generate_web_map_config_from_environment_writes_browser_keys(
    tmp_path: Path,
) -> None:
    amap_target, tencent_target = generate_web_map_config_from_environment(
        {
            "AMAP_JS_API_KEY": "browser-amap-key",
            "AMAP_JS_SECURITY_CODE": "browser-amap-security",
            "TENCENT_SEARCH_KEY": "browser-tencent-key",
            "RECOMMENDATION_API_BASE_URL": "https://api.example.com/api/v1",
        },
        tmp_path / "web",
    )

    assert "browser-amap-key" in amap_target.read_text(encoding="utf-8")
    tencent_content = tencent_target.read_text(encoding="utf-8")
    assert "browser-tencent-key" in tencent_content
    assert 'window.XUHUI_RECOMMENDATION_API_BASE_URL = "https://api.example.com/api/v1";' in (
        tencent_content
    )


def test_launchers_call_web_map_config_source_file() -> None:
    powershell_launcher = (REPOSITORY_ROOT / "start-local-app.ps1").read_text(
        encoding="utf-8-sig"
    )
    bash_launcher = (REPOSITORY_ROOT / "start-local-app.sh").read_text(encoding="utf-8")

    assert "src\\xuhui_route_builder\\web_map_config.py" in powershell_launcher
    assert "src/xuhui_route_builder/web_map_config.py" in bash_launcher
