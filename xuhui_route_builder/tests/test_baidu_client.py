from pathlib import Path

import pytest

from xuhui_route_builder.baidu_client import BaiduClient


def test_place_region_uses_gcj02_and_xuhui_region(tmp_path: Path, monkeypatch) -> None:
    captured = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": 0, "message": "ok", "results": []}

    def fake_get(url, **kwargs):
        captured.append((url, kwargs))
        return Response()

    monkeypatch.setattr("xuhui_route_builder.baidu_client.requests.get", fake_get)
    client = BaiduClient("test-ak", tmp_path)

    record = client.place_region("上海植物园三号门")

    assert record.status == 0
    assert record.cache_hit is False
    assert captured[0][1]["params"]["region"] == "上海市徐汇区"
    assert captured[0][1]["params"]["ret_coordtype"] == "gcj02ll"
    assert captured[0][1]["params"]["ak"] == "test-ak"


def test_repeated_baidu_query_reads_cache_without_network(
    tmp_path: Path, monkeypatch
) -> None:
    call_count = 0

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": 0, "message": "ok", "results": []}

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return Response()

    monkeypatch.setattr("xuhui_route_builder.baidu_client.requests.get", fake_get)
    client = BaiduClient("test-ak", tmp_path)

    first = client.place_region("龙华寺")
    second = client.place_region("龙华寺")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert call_count == 1


def test_baidu_cache_hash_does_not_include_access_key(tmp_path: Path) -> None:
    first = BaiduClient("first-ak", tmp_path)
    second = BaiduClient("second-ak", tmp_path)
    params = {"query": "龙华寺", "region": "上海市徐汇区"}

    assert first._hash_params("place_region", params) == second._hash_params(
        "place_region", params
    )


def test_failed_baidu_response_is_not_cached(tmp_path: Path, monkeypatch) -> None:
    call_count = 0

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": 211, "message": "APP SN validation failed"}

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return Response()

    monkeypatch.setattr("xuhui_route_builder.baidu_client.requests.get", fake_get)
    client = BaiduClient("test-ak", tmp_path)

    first = client.place_region("龙华寺")
    second = client.place_region("龙华寺")

    assert first.status == second.status == 211
    assert call_count == 2
    assert list(tmp_path.glob("*.json")) == []


def test_baidu_response_uses_type_error_for_non_object_payload(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list:
            return []

    monkeypatch.setattr(
        "xuhui_route_builder.baidu_client.requests.get",
        lambda *args, **kwargs: Response(),
    )

    with pytest.raises(TypeError, match="Baidu response invalid"):
        BaiduClient("test-ak", tmp_path).place_region("龙华寺")
