import json
from pathlib import Path

from xuhui_route_builder.osm_poi import OSM_POI_QUERY, build_osm_poi_index


def test_build_osm_poi_index_writes_named_point_and_way_centers(tmp_path: Path) -> None:
    class Client:
        def query(self, query: str) -> dict:
            assert query == OSM_POI_QUERY
            return {
                "elements": [
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 31.17,
                        "lon": 121.42,
                        "tags": {"name": "康健园", "leisure": "park"},
                    },
                    {
                        "type": "way",
                        "id": 3,
                        "center": {"lat": 31.18, "lon": 121.43},
                        "tags": {
                            "name:zh": "桂林公园",
                            "name": "Guilin Park",
                            "leisure": "park",
                        },
                    },
                    {"type": "way", "id": 4, "tags": {"name": "缺少中心点"}},
                ]
            }

    output = tmp_path / "osm_poi_index.json"
    pois = build_osm_poi_index(Client(), output)

    assert [poi["name"] for poi in pois] == ["康健园", "桂林公园"]
    assert pois[1]["lng_wgs84"] == 121.43
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["source"] == "OpenStreetMap"
    assert document["pois"] == pois
