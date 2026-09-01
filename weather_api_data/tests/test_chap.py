# pyright: reportUnknownMemberType=false

import json
from datetime import date
from pathlib import Path

import numpy as np
import xarray as xr
from shapely.geometry import Polygon

from weather_api_data.chap import build_xuhui_year, crop_daily_dataset, parse_chap_date


def test_crop_daily_dataset_keeps_only_grid_centers_inside_boundary() -> None:
    dataset = xr.Dataset(
        data_vars=(
            {
                "PM2.5": (
                    ("lat", "lon"),
                    np.array(
                        [
                            [1.0, 2.0, 3.0],
                            [4.0, 5.0, 6.0],
                            [7.0, 8.0, 9.0],
                        ],
                        dtype=np.float32,
                    ),
                    {"units": "ug/m3"},
                )
            }
        ),
        coords={
            "lat": np.array([31.09, 31.15, 31.21]),
            "lon": np.array([121.39, 121.42, 121.48]),
        },
    )
    boundary = Polygon(
        [
            (121.40, 31.10),
            (121.45, 31.10),
            (121.45, 31.20),
            (121.40, 31.20),
        ]
    )

    result = crop_daily_dataset(dataset, boundary, date(2025, 1, 1))

    assert result.sizes == {"time": 1, "lat": 1, "lon": 1}
    assert result["pm2_5_ug_m3"].item() == 5.0
    assert result["xuhui_mask"].item() == 1
    assert str(result["time"].dt.date.item()) == "2025-01-01"


def test_parse_chap_date_reads_daily_filename() -> None:
    assert parse_chap_date("CHAP_PM2.5_D1K_20251231_V4.nc") == date(2025, 12, 31)


def test_build_xuhui_year_combines_daily_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "daily"
    input_dir.mkdir()
    for day, value in (("20250101", 5.0), ("20250102", 6.0)):
        dataset = xr.Dataset(
            {"PM2.5": (("lat", "lon"), np.array([[value]], dtype=np.float32))},
            coords={"lat": [31.15], "lon": [121.42]},
        )
        dataset.to_netcdf(
            input_dir / f"CHAP_PM2.5_D1K_{day}_V4.nc",
            engine="h5netcdf",
        )

    boundary_path = tmp_path / "xuhui.geojson"
    boundary_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [121.40, 31.10],
                                    [121.45, 31.10],
                                    [121.45, 31.20],
                                    [121.40, 31.20],
                                    [121.40, 31.10],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "xuhui_2025.nc"

    report = build_xuhui_year(
        input_dir=input_dir,
        boundary_path=boundary_path,
        output_path=output_path,
        start_on=date(2025, 1, 1),
        end_on=date(2025, 1, 2),
    )

    with xr.open_dataset(output_path, engine="h5netcdf") as result:
        assert result.sizes == {"time": 2, "lat": 1, "lon": 1}
        assert result["pm2_5_ug_m3"].values[:, 0, 0].tolist() == [5.0, 6.0]
    assert report == {"days": 2, "valid_grid_cells": 1}
