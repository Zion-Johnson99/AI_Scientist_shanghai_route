from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ENDPOINTS = {
    "place_region": "https://api.map.baidu.com/place/v3/region",
    "geocode": "https://api.map.baidu.com/geocoding/v3/",
}


@dataclass(frozen=True)
class BaiduRawRecord:
    endpoint: str
    params_hash: str
    status: int | None
    message: str | None
    raw_path: str
    payload: dict[str, Any]
    cache_hit: bool


class BaiduClient:
    def __init__(self, access_key: str, cache_dir: Path, timeout_s: int = 20) -> None:
        if not access_key.strip():
            raise ValueError("BAIDU_MAP_AK is required")
        self.access_key = access_key.strip()
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def request(
        self, endpoint: str, params: dict[str, Any], *, allow_network: bool = True
    ) -> BaiduRawRecord:
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Unsupported Baidu endpoint: {endpoint}")
        params_hash = self._hash_params(endpoint, params)
        raw_path = self.cache_dir / f"{endpoint}_{params_hash}.json"
        if raw_path.exists():
            payload = self._read_cache(raw_path, endpoint, params_hash)
            if payload.get("status") == 0:
                return self._record(
                    endpoint, params_hash, raw_path, payload, cache_hit=True
                )
        if not allow_network:
            raise RuntimeError(
                f"Baidu network request budget exhausted: endpoint={endpoint}, query_hash={params_hash}"
            )

        prepared = {"ak": self.access_key, "output": "json", **params}
        try:
            response = requests.get(
                ENDPOINTS[endpoint], params=prepared, timeout=self.timeout_s
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Baidu request failed: endpoint={endpoint}, query_hash={params_hash}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Baidu response invalid: endpoint={endpoint}, query_hash={params_hash}"
            )
        if payload.get("status") == 0:
            self._write_cache(raw_path, payload)
        return self._record(endpoint, params_hash, raw_path, payload, cache_hit=False)

    def place_region(
        self, query: str, region: str = "上海市徐汇区", *, allow_network: bool = True
    ) -> BaiduRawRecord:
        return self.request(
            "place_region",
            {
                "query": query,
                "region": region,
                "extensions_adcode": "true",
                "ret_coordtype": "gcj02ll",
                "page_size": 20,
                "page_num": 0,
                "scope": 1,
            },
            allow_network=allow_network,
        )

    def geocode(
        self, address: str, city: str = "上海市", *, allow_network: bool = True
    ) -> BaiduRawRecord:
        return self.request(
            "geocode",
            {"address": address, "city": city, "ret_coordtype": "gcj02ll"},
            allow_network=allow_network,
        )

    @staticmethod
    def _hash_params(endpoint: str, params: dict[str, Any]) -> str:
        value = json.dumps(
            {"endpoint": endpoint, "params": params}, sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _read_cache(raw_path: Path, endpoint: str, params_hash: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Baidu cache invalid: endpoint={endpoint}, query_hash={params_hash}, path={raw_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Baidu cache invalid: endpoint={endpoint}, query_hash={params_hash}, path={raw_path}"
            )
        return payload

    @staticmethod
    def _write_cache(raw_path: Path, payload: dict[str, Any]) -> None:
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=raw_path.parent,
                prefix=f".{raw_path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                temporary_path = handle.name
            os.replace(temporary_path, raw_path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    @staticmethod
    def _record(
        endpoint: str,
        params_hash: str,
        raw_path: Path,
        payload: dict[str, Any],
        *,
        cache_hit: bool,
    ) -> BaiduRawRecord:
        status = payload.get("status")
        return BaiduRawRecord(
            endpoint=endpoint,
            params_hash=params_hash,
            status=int(status)
            if isinstance(status, int | str) and str(status).lstrip("-").isdigit()
            else None,
            message=str(payload.get("message"))
            if payload.get("message") is not None
            else None,
            raw_path=str(raw_path),
            payload=payload,
            cache_hit=cache_hit,
        )
