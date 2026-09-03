"""Web adapter surface: resolves the published local product and its payload."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parent
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
PAYLOAD_RELATIVE: str = "publish/research_harness_latest.json"
INDEX_RELATIVE: str = "index.html"
PRODUCT_RELATIVE: str = "publish/local-product"
REQUIRED_PAYLOAD_KEYS: tuple[str, ...] = (
    "run_id",
    "generated_at",
    "status",
    "research_question",
    "hypothesis",
)


class WebProductError(RuntimeError):
    """Raised when the published web product or its payload is unusable."""


@dataclass(frozen=True)
class WebProductResult:
    """Immutable summary of the published local web product."""

    payload_path: str
    index_path: str
    payload_present: bool
    index_present: bool
    asset_count: int
    total_bytes: int
    missing_payload_keys: tuple[str, ...]
    external_references: tuple[str, ...]
    passed: bool
    errors: tuple[str, ...]


def payload_path(root: Path | None = None) -> Path:
    """Return the run-relative research payload path."""
    return (root or RUN_ROOT) / PAYLOAD_RELATIVE


def product_root(root: Path | None = None) -> Path:
    """Return the published local product directory."""
    return (root or RUN_ROOT) / PRODUCT_RELATIVE


def _external_references(index: Path) -> tuple[str, ...]:
    if not index.is_file():
        return ()
    text = index.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for marker in ("<script src=", "<link href=", "<img src=", "@import"):
        position = 0
        while True:
            found = text.find(marker, position)
            if found < 0:
                break
            snippet = text[found : found + len(marker) + 120]
            if "http://" in snippet or "https://" in snippet or "//" in snippet.split('"')[-1]:
                quote = snippet.split(marker, 1)[1].strip().lstrip("=").strip()
                if quote.startswith(("http://", "https://", "//")):
                    hits.append(marker.strip())
            position = found + len(marker)
    return tuple(sorted(set(hits)))


def audit(root: Path | None = None) -> WebProductResult:
    """Check the payload keys, the index file and offline-only asset references."""
    base = root or RUN_ROOT
    payload = payload_path(base)
    product = product_root(base)
    index = product / INDEX_RELATIVE
    errors: list[str] = []
    missing_keys: list[str] = []
    if payload.is_file():
        try:
            with payload.open("r", encoding="utf-8") as handle:
                data: Any = json.load(handle)
        except json.JSONDecodeError as exc:
            raise WebProductError("research_harness_latest.json 无法解析") from exc
        if not isinstance(data, dict):
            errors.append("payload_not_object")
        else:
            missing_keys = [k for k in REQUIRED_PAYLOAD_KEYS if not data.get(k)]
            if missing_keys:
                errors.append("payload_required_key_missing")
    else:
        errors.append("payload_missing")
    if not index.is_file():
        errors.append("index_missing")
    assets = sorted(p for p in product.rglob("*") if p.is_file())
    external = _external_references(index)
    if external:
        errors.append("external_asset_reference")
    return WebProductResult(
        payload_path=str(payload.relative_to(base)) if payload.is_relative_to(base) else payload.name,
        index_path=str(index.relative_to(product)) if index.is_file() else INDEX_RELATIVE,
        payload_present=payload.is_file(),
        index_present=index.is_file(),
        asset_count=len(assets),
        total_bytes=sum(p.stat().st_size for p in assets),
        missing_payload_keys=tuple(missing_keys),
        external_references=external,
        passed=not errors,
        errors=tuple(errors),
    )


def as_dict(result: WebProductResult) -> dict[str, Any]:
    """Serialise a WebProductResult for JSON output."""
    return {
        "payload_path": result.payload_path,
        "index_path": result.index_path,
        "payload_present": result.payload_present,
        "index_present": result.index_present,
        "asset_count": result.asset_count,
        "total_bytes": result.total_bytes,
        "missing_payload_keys": list(result.missing_payload_keys),
        "external_references": list(result.external_references),
        "passed": result.passed,
        "errors": list(result.errors),
    }
