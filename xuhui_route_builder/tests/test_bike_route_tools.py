import importlib.util
from pathlib import Path

import pytest


def _load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tools/rebuild_bike_routes.py"
    spec = importlib.util.spec_from_file_location("rebuild_bike_routes", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bike_rebuild_has_exactly_thirty_scoped_specs() -> None:
    tool = _load_tool()

    assert len(tool.ROUTE_SPECS) == 30
    assert set(tool.ROUTE_SPECS) == {
        f"XH_BIKE_{index:04d}" for index in range(61, 91)
    }


def test_bike_rebuild_rejects_batches_above_five() -> None:
    tool = _load_tool()
    route_ids = list(tool.ROUTE_SPECS)[:6]

    with pytest.raises(ValueError, match="at most five"):
        tool.select_specs(route_ids)


def test_bike_rebuild_refuses_to_write_a_failed_route() -> None:
    tool = _load_tool()

    with pytest.raises(RuntimeError, match="refusing to write failed routes"):
        tool.apply_routes(
            tool.PROJECT_ROOT,
            {"XH_BIKE_0061": {}},
            {"XH_BIKE_0061": {"status": "fail"}},
        )


def test_bike_browser_uses_riding_service_and_separate_cache() -> None:
    tool = _load_tool()
    expression = tool.browser_batch_expression(
        {"XH_BIKE_0061": tool.ROUTE_SPECS["XH_BIKE_0061"]}
    )

    assert "new AMap.Riding" in expression
    assert "riding timeout" in expression
    assert "__xuhuiBikeCache" in expression
    assert "__xuhuiBikeBatch" in expression


def test_0088_starts_from_the_xuhui_side_of_hengfu() -> None:
    tool = _load_tool()

    assert tool.ROUTE_SPECS["XH_BIKE_0088"]["nodes"][:2] == [
        "复兴中路与嘉善路交叉口",
        "中山南二路与天钥桥路交叉口",
    ]
