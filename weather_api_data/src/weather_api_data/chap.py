# pyright: reportUnknownMemberType=false

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import geopandas as gpd
import numpy as np
import xarray as xr
from shapely import intersects_xy
from shapely.geometry.base import BaseGeometry

LOGGER = logging.getLogger(__name__)


class ChapProcessingError(RuntimeError):
    """Raised when a CHAP file cannot be validated or cropped."""


def _find_name(available: set[str], candidates: tuple[str, ...], kind: str) -> str:
    for candidate in candidates:
        if candidate in available:
            return candidate
    raise ChapProcessingError(f"CHAP dataset has no supported {kind}: {sorted(available)}")


def parse_chap_date(filename: str) -> date:
    match = re.fullmatch(r"CHAP_PM2\.5_D1K_(\d{8})_V4\.nc", filename)
    if match is None:
        raise ChapProcessingError(f"Unexpected CHAP daily filename: {filename}")
    value = match.group(1)
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")


def build_xuhui_year(
    *,
    input_dir: Path,
    boundary_path: Path,
    output_path: Path,
    start_on: date,
    end_on: date,
) -> dict[str, int]:
    if start_on > end_on:
        raise ChapProcessingError("CHAP start date is after end date")
    if not input_dir.is_dir():
        raise ChapProcessingError(f"CHAP daily input directory is missing: {input_dir}")

    boundary_frame = gpd.read_file(boundary_path)
    if boundary_frame.empty:
        raise ChapProcessingError(f"Xuhui boundary file has no features: {boundary_path}")
    if boundary_frame.crs is None:
        boundary_frame = boundary_frame.set_crs("EPSG:4326")
    else:
        boundary_frame = boundary_frame.to_crs("EPSG:4326")
    boundary = boundary_frame.geometry.union_all()
    if boundary.is_empty or not boundary.is_valid:
        raise ChapProcessingError(f"Xuhui boundary is empty or invalid: {boundary_path}")

    expected_dates: list[date] = []
    current = start_on
    while current <= end_on:
        expected_dates.append(current)
        current += timedelta(days=1)

    daily_paths: dict[date, Path] = {}
    for path in input_dir.glob("CHAP_PM2.5_D1K_*_V4.nc"):
        observed_on = parse_chap_date(path.name)
        if observed_on in daily_paths:
            raise ChapProcessingError(f"Duplicate CHAP date: {observed_on.isoformat()}")
        daily_paths[observed_on] = path
    missing_dates = [value for value in expected_dates if value not in daily_paths]
    extra_dates = [value for value in daily_paths if value not in expected_dates]
    if missing_dates or extra_dates:
        raise ChapProcessingError(
            "CHAP daily coverage mismatch: "
            f"missing={[value.isoformat() for value in missing_dates[:5]]}, "
            f"extra={[value.isoformat() for value in extra_dates[:5]]}"
        )

    LOGGER.info(
        "Cropping CHAP daily files input_dir=%s output_path=%s start=%s end=%s days=%d",
        input_dir,
        output_path,
        start_on,
        end_on,
        len(expected_dates),
    )
    daily_frames: list[xr.Dataset] = []
    for index, observed_on in enumerate(expected_dates, start=1):
        path = daily_paths[observed_on]
        try:
            with xr.open_dataset(path, engine="h5netcdf") as source:
                daily_frames.append(crop_daily_dataset(source, boundary, observed_on).load())
        except Exception as exc:
            raise ChapProcessingError(
                f"Failed to process CHAP file date={observed_on.isoformat()} path={path}"
            ) from exc
        if index == 1 or index % 50 == 0 or index == len(expected_dates):
            LOGGER.info(
                "Processed CHAP daily files completed=%d total=%d", index, len(expected_dates)
            )

    annual = xr.concat(
        daily_frames,
        dim="time",
        data_vars="minimal",
        coords="minimal",
        compat="override",
        join="exact",
    )
    annual.attrs.update(
        {
            "title": "CHAP ChinaHighPM2.5 daily 1 km estimates for Xuhui District",
            "coverage_start": start_on.isoformat(),
            "coverage_end": end_on.isoformat(),
            "source_record": "https://zenodo.org/records/21770406",
            "source_version": "V4",
            "license": "CC BY 4.0",
            "boundary_source": str(boundary_path.resolve()),
            "grid_selection": "grid center intersects Xuhui boundary",
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    annual.to_netcdf(
        output_path,
        engine="h5netcdf",
        encoding={
            "pm2_5_ug_m3": {
                "dtype": "float32",
                "zlib": True,
                "complevel": 4,
                "_FillValue": np.float32(-9999.0),
            },
            "xuhui_mask": {"dtype": "uint8", "zlib": True, "complevel": 4},
        },
    )
    valid_grid_cells = int(annual["xuhui_mask"].sum().item())
    LOGGER.info(
        "Wrote Xuhui CHAP dataset output_path=%s days=%d valid_grid_cells=%d",
        output_path,
        len(expected_dates),
        valid_grid_cells,
    )
    return {"days": len(expected_dates), "valid_grid_cells": valid_grid_cells}


def crop_daily_dataset(
    dataset: xr.Dataset,
    boundary: BaseGeometry,
    observed_on: date,
) -> xr.Dataset:
    if boundary.is_empty or not boundary.is_valid:
        raise ChapProcessingError("Xuhui boundary geometry is empty or invalid")

    coordinate_names = {str(name) for name in dataset.coords}
    latitude_name = _find_name(coordinate_names, ("lat", "latitude"), "latitude")
    longitude_name = _find_name(coordinate_names, ("lon", "longitude"), "longitude")
    variable_name = _find_name(
        {str(name) for name in dataset.data_vars},
        ("PM2.5", "PM2_5", "pm2_5", "pm25"),
        "PM2.5 variable",
    )

    min_longitude, min_latitude, max_longitude, max_latitude = boundary.bounds
    longitude = dataset[longitude_name]
    latitude = dataset[latitude_name]
    selected_longitude = longitude.where(
        (longitude >= min_longitude) & (longitude <= max_longitude),
        drop=True,
    )
    selected_latitude = latitude.where(
        (latitude >= min_latitude) & (latitude <= max_latitude),
        drop=True,
    )
    if selected_longitude.size == 0 or selected_latitude.size == 0:
        raise ChapProcessingError("CHAP grid does not overlap the Xuhui boundary extent")

    cropped = dataset.sel({longitude_name: selected_longitude, latitude_name: selected_latitude})
    longitude_values = np.asarray(cast(object, cropped[longitude_name].values), dtype=np.float64)
    latitude_values = np.asarray(cast(object, cropped[latitude_name].values), dtype=np.float64)
    longitude_grid, latitude_grid = np.meshgrid(
        longitude_values,
        latitude_values,
    )
    mask_values = intersects_xy(boundary, longitude_grid, latitude_grid)
    if not bool(mask_values.any()):
        raise ChapProcessingError("No CHAP grid centers fall inside the Xuhui boundary")

    mask = xr.DataArray(
        mask_values,
        coords={
            latitude_name: cropped[latitude_name],
            longitude_name: cropped[longitude_name],
        },
        dims=(latitude_name, longitude_name),
    )
    pm2_5 = cropped[variable_name].astype(np.float32).where(mask)
    pm2_5.attrs = dict(cropped[variable_name].attrs)
    pm2_5.attrs["units"] = "ug/m3"
    pm2_5 = pm2_5.expand_dims(time=[np.datetime64(observed_on)])

    return xr.Dataset(
        data_vars={
            "pm2_5_ug_m3": pm2_5,
            "xuhui_mask": mask.astype(np.uint8),
        },
        attrs={
            "provider": "CHAP",
            "dataset": "ChinaHighPM2.5",
            "spatial_basis": "grid_1km",
            "temporal_resolution": "daily",
            "is_estimated": "true",
        },
    )
