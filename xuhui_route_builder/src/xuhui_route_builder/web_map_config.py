from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values


class WebMapConfigError(RuntimeError):
    """Raised when local browser map configuration cannot be generated."""


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
    amap_key = _required_value(values, "AMAP_JS_API_KEY")
    amap_security_code = _required_value(values, "AMAP_JS_SECURITY_CODE")
    tencent_search_key = _required_value(values, "TENCENT_SEARCH_KEY")

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
        "window.XUHUI_TENCENT_SEARCH_KEY = "
        f"{json.dumps(tencent_search_key, ensure_ascii=False)};\n",
    )
    return amap_target, tencent_target


def main() -> None:
    parser = argparse.ArgumentParser(description="生成本地网页地图配置")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--web-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        generate_web_map_config(args.env_file, args.web_root)
    except WebMapConfigError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
