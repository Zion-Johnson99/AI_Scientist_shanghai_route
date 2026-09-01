from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values


class WebMapConfigError(RuntimeError):
    """Raised when local browser map configuration cannot be generated."""


_LOCAL_RECOMMENDATION_API = "http://127.0.0.1:8124/api/v1"


def _required_value(values: Mapping[str, object], name: str) -> str:
    value = str(values.get(name) or "").strip()
    if not value or value.startswith("replace-with-your-"):
        raise WebMapConfigError(f"{name} 未配置")
    return value


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def generate_web_map_config(env_file: Path, web_root: Path) -> tuple[Path, Path]:
    if not env_file.is_file():
        raise WebMapConfigError(f"缺少路线配置文件：{env_file}")

    values = dotenv_values(env_file, encoding="utf-8-sig")
    return generate_web_map_config_from_environment(values, web_root)


def generate_web_map_config_from_environment(
    values: Mapping[str, object], web_root: Path
) -> tuple[Path, Path]:
    amap_key = _required_value(values, "AMAP_JS_API_KEY")
    amap_security_code = _required_value(values, "AMAP_JS_SECURITY_CODE")
    tencent_search_key = _required_value(values, "TENCENT_SEARCH_KEY")
    recommendation_api_base_url = str(
        values.get("RECOMMENDATION_API_BASE_URL") or _LOCAL_RECOMMENDATION_API
    ).strip().rstrip("/")
    if not recommendation_api_base_url.startswith(("https://", "http://127.0.0.1:")):
        raise WebMapConfigError("RECOMMENDATION_API_BASE_URL 需为 HTTPS 地址")

    amap_target = web_root / "local-amap-config.js"
    tencent_target = web_root / "local-tencent-config.js"
    _write_atomic(
        amap_target,
        "\n".join(
            (
                f"window.XUHUI_AMAP_JS_KEY = {json.dumps(amap_key, ensure_ascii=False)};",
                "window.XUHUI_AMAP_JS_SECURITY_CODE = "
                f"{json.dumps(amap_security_code, ensure_ascii=False)};",
                "",
            )
        ),
    )
    _write_atomic(
        tencent_target,
        "\n".join(
            (
                "window.XUHUI_TENCENT_SEARCH_KEY = "
                f"{json.dumps(tencent_search_key, ensure_ascii=False)};",
                "window.XUHUI_RECOMMENDATION_API_BASE_URL = "
                f"{json.dumps(recommendation_api_base_url, ensure_ascii=False)};",
                "",
            )
        ),
    )
    return amap_target, tencent_target


def main() -> None:
    parser = argparse.ArgumentParser(description="生成网页地图配置")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env-file", type=Path)
    source.add_argument("--from-environment", action="store_true")
    parser.add_argument("--web-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.from_environment:
            generate_web_map_config_from_environment(os.environ, args.web_root)
        else:
            assert args.env_file is not None
            generate_web_map_config(args.env_file, args.web_root)
    except WebMapConfigError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
