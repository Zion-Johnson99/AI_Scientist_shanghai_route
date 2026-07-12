from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import requests

from .models import AmapRawRecord


ENDPOINTS = {
    "district": "https://restapi.amap.com/v3/config/district",
    "geocode": "https://restapi.amap.com/v3/geocode/geo",
    "regeo": "https://restapi.amap.com/v3/geocode/regeo",
    "place_text": "https://restapi.amap.com/v3/place/text",
    "place_around": "https://restapi.amap.com/v3/place/around",
    "place_polygon": "https://restapi.amap.com/v3/place/polygon",
    "place_detail": "https://restapi.amap.com/v3/place/detail",
    "place_text_v5": "https://restapi.amap.com/v5/place/text",
    "place_around_v5": "https://restapi.amap.com/v5/place/around",
    "place_polygon_v5": "https://restapi.amap.com/v5/place/polygon",
    "walking_v2": "https://restapi.amap.com/v5/direction/walking",
    "bicycling_v2": "https://restapi.amap.com/v5/direction/bicycling",
    "walking": "https://restapi.amap.com/v3/direction/walking",
    "bicycling": "https://restapi.amap.com/v4/direction/bicycling",
    "driving": "https://restapi.amap.com/v3/direction/driving",
    "transit": "https://restapi.amap.com/v3/direction/transit/integrated",
}


class AmapClient:
    def __init__(
        self,
        web_service_key: str,
        cache_dir: Path,
        timeout_s: int = 20,
        qps_retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not web_service_key.strip():
            raise ValueError("AMAP_WEB_SERVICE_KEY is required")
        self.web_service_key = web_service_key.strip()
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.qps_retry_delays = qps_retry_delays
        self.sleep_fn = sleep_fn
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def prepare_request(self, endpoint: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Unsupported Amap endpoint: {endpoint}")
        prepared = {"key": self.web_service_key, "output": "JSON", **params}
        return ENDPOINTS[endpoint], prepared

    def request(self, endpoint: str, params: dict[str, Any]) -> AmapRawRecord:
        url, prepared = self.prepare_request(endpoint, params)
        payload: dict[str, Any] = {}
        for attempt in range(len(self.qps_retry_delays) + 1):
            response = requests.get(url, params=prepared, timeout=self.timeout_s)
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("infocode", "")) != "10021" or attempt == len(self.qps_retry_delays):
                break
            self.sleep_fn(self.qps_retry_delays[attempt])
        params_hash = self._hash_params(endpoint, prepared)
        raw_path = self.cache_dir / f"{endpoint}_{params_hash}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return AmapRawRecord(
            endpoint=endpoint,
            params_hash=params_hash,
            status=str(payload.get("status", "")),
            info=payload.get("info"),
            infocode=payload.get("infocode"),
            raw_path=str(raw_path),
            payload=payload,
        )

    def district(self, keywords: str = "徐汇区") -> AmapRawRecord:
        return self.request("district", {"keywords": keywords, "subdistrict": 0, "extensions": "all"})

    def geocode(self, address: str, city: str = "上海") -> AmapRawRecord:
        return self.request("geocode", {"address": address, "city": city})

    def regeo(self, location: str, radius: int = 1000) -> AmapRawRecord:
        return self.request("regeo", {"location": location, "radius": radius, "extensions": "all"})

    def place_text(self, keywords: str, city: str = "上海", types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"keywords": keywords, "city": city, "citylimit": "true", "extensions": "all"}
        if types:
            params["types"] = types
        return self.request("place_text", params)

    def place_around(self, location: str, radius: int, keywords: str | None = None, types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"location": location, "radius": radius, "extensions": "all"}
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        return self.request("place_around", params)

    def place_polygon(self, polygon: str, keywords: str | None = None, types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"polygon": polygon, "extensions": "all"}
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        return self.request("place_polygon", params)

    def place_text_v5(self, keywords: str, region: str = "310104", types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"keywords": keywords, "region": region, "show_fields": "business,navi"}
        if types:
            params["types"] = types
        return self.request("place_text_v5", params)

    def place_around_v5(self, location: str, radius: int, keywords: str | None = None, types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"location": location, "radius": radius, "show_fields": "business,navi"}
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        return self.request("place_around_v5", params)

    def place_polygon_v5(self, polygon: str, keywords: str | None = None, types: str | None = None) -> AmapRawRecord:
        params: dict[str, Any] = {"polygon": polygon, "show_fields": "business,navi"}
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        return self.request("place_polygon_v5", params)

    def walking(self, origin: str, destination: str) -> AmapRawRecord:
        return self.request("walking", {"origin": origin, "destination": destination})

    def bicycling(self, origin: str, destination: str) -> AmapRawRecord:
        return self.request("bicycling", {"origin": origin, "destination": destination})

    def walking_v2(self, origin: str, destination: str) -> AmapRawRecord:
        return self.request(
            "walking_v2",
            {"origin": origin, "destination": destination, "show_fields": "cost,polyline"},
        )

    def bicycling_v2(self, origin: str, destination: str) -> AmapRawRecord:
        return self.request(
            "bicycling_v2",
            {"origin": origin, "destination": destination, "show_fields": "cost,polyline"},
        )

    def driving(self, origin: str, destination: str) -> AmapRawRecord:
        return self.request("driving", {"origin": origin, "destination": destination, "extensions": "all"})

    def transit(self, origin: str, destination: str, city: str = "上海") -> AmapRawRecord:
        return self.request("transit", {"origin": origin, "destination": destination, "city": city})

    @staticmethod
    def _hash_params(endpoint: str, params: dict[str, Any]) -> str:
        payload = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
