from __future__ import annotations

import sys

from xuhui_route_builder import cli


def test_cache_route_batch_command_dispatches_without_network(
    monkeypatch, capsys
) -> None:
    captured = {}

    def fake_cache(project_root, target_id, route_ids, proxy_url):
        captured.update(
            project_root=project_root,
            target_id=target_id,
            route_ids=route_ids,
            proxy_url=proxy_url,
        )
        return {
            "route_count": 2,
            "segment_count": 5,
            "cache_hits": 3,
            "fetched": 2,
        }

    monkeypatch.setattr(cli, "cache_route_batch", fake_cache, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xuhui-route-builder",
            "cache-route-batch",
            "--target-id",
            "browser-target",
            "--route-id",
            "XH_RUN_0031",
            "--route-id",
            "XH_RUN_0032",
            "--proxy-url",
            "http://127.0.0.1:3456",
        ],
    )

    cli.main()

    assert captured["target_id"] == "browser-target"
    assert captured["route_ids"] == ["XH_RUN_0031", "XH_RUN_0032"]
    assert captured["proxy_url"] == "http://127.0.0.1:3456"
    assert "route_count=2" in capsys.readouterr().out
