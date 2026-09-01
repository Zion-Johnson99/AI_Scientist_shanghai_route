from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = PROJECT_ROOT / "scripts" / "build_route_media_assets.py"


def test_materialize_can_recompress_webp_in_place(tmp_path: Path) -> None:
    image_path = tmp_path / "in-place.webp"
    program = """
import importlib.util
import pathlib
import sys
from PIL import Image

builder_path = pathlib.Path(sys.argv[1])
image_path = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("route_media_builder", builder_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Image.new("RGB", (1440, 1080), "green").save(image_path, "WEBP")
original_save = Image.Image.save
def reject_direct_overwrite(self, fp, *args, **kwargs):
    if pathlib.Path(fp).resolve() == image_path.resolve():
        raise OSError("direct overwrite is unsafe")
    return original_save(self, fp, *args, **kwargs)
module.Image.Image.save = reject_direct_overwrite
module.materialize(image_path, image_path)
with Image.open(image_path) as image:
    assert max(image.size) == 1280
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(BUILDER_PATH), str(image_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, completed.stderr
