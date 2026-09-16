from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from ..config import (
    MAP_DIR,
    MAP_YAML_PATH,
)


# ============================================================
# Map Metadata
# ============================================================

def load_map_metadata() -> dict[str, Any]:

    if not MAP_YAML_PATH.exists():

        raise FileNotFoundError(
            f"Map YAML 파일 없음: {MAP_YAML_PATH}"
        )

    with MAP_YAML_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        map_yaml = yaml.safe_load(file)

    image_name = map_yaml["image"]

    image_path = Path(image_name)

    if not image_path.is_absolute():
        image_path = MAP_DIR / image_name

    if not image_path.exists():

        raise FileNotFoundError(
            f"Map 이미지 파일 없음: {image_path}"
        )

    with Image.open(image_path) as image:

        width, height = image.size

    origin = map_yaml["origin"]

    resolution = float(
        map_yaml["resolution"]
    )

    return {

        "yaml_path": str(
            MAP_YAML_PATH
        ),

        "image_path": str(
            image_path
        ),

        "image_name": image_path.name,

        "resolution": resolution,

        "origin": origin,

        "negate": int(
            map_yaml.get(
                "negate",
                0,
            )
        ),

        "occupied_thresh": float(
            map_yaml.get(
                "occupied_thresh",
                0.65,
            )
        ),

        "free_thresh": float(
            map_yaml.get(
                "free_thresh",
                0.25,
            )
        ),

        "width": width,

        "height": height,

        "frame": "map",
    }


# ============================================================
# Frontend 공개용 map 정보
# ============================================================

def get_public_map_info() -> dict[str, Any]:

    info = load_map_metadata()

    # 서버 내부 경로는 프론트로 보내지 않음
    info.pop(
        "yaml_path",
        None,
    )

    info.pop(
        "image_path",
        None,
    )

    info["image_url"] = (
        "/api/map/image"
    )

    info["world_bounds"] = (
        get_world_bounds(info)
    )

    return info


# ============================================================
# Map world 영역
# ============================================================

def get_world_bounds(
    map_info: dict[str, Any] | None = None,
) -> dict[str, float]:

    info = (
        map_info
        or load_map_metadata()
    )

    origin_x = float(
        info["origin"][0]
    )

    origin_y = float(
        info["origin"][1]
    )

    resolution = float(
        info["resolution"]
    )

    width = int(
        info["width"]
    )

    height = int(
        info["height"]
    )

    return {

        "min_x": origin_x,

        "min_y": origin_y,

        "max_x": (
            origin_x
            + width * resolution
        ),

        "max_y": (
            origin_y
            + height * resolution
        ),
    }


# ============================================================
# ROS world 좌표 -> image pixel 좌표
# ============================================================

def world_to_pixel(
    x: float,
    y: float,
) -> tuple[float, float]:

    """
    ROS Map

        +y
        ↑
        |
        +----→ +x

    Image

        +----→ +x
        |
        ↓
        +y

    따라서 image의 Y축을 뒤집어야 한다.
    """

    info = load_map_metadata()

    origin_x = float(
        info["origin"][0]
    )

    origin_y = float(
        info["origin"][1]
    )

    resolution = float(
        info["resolution"]
    )

    height = float(
        info["height"]
    )

    px = (
        float(x)
        - origin_x
    ) / resolution

    py = (
        height
        - (
            (
                float(y)
                - origin_y
            )
            / resolution
        )
    )

    return px, py


# ============================================================
# image pixel -> ROS world 좌표
# ============================================================

def pixel_to_world(
    px: float,
    py: float,
) -> tuple[float, float]:

    info = load_map_metadata()

    origin_x = float(
        info["origin"][0]
    )

    origin_y = float(
        info["origin"][1]
    )

    resolution = float(
        info["resolution"]
    )

    height = float(
        info["height"]
    )

    x = (
        origin_x
        + float(px)
        * resolution
    )

    y = (
        origin_y
        + (
            height
            - float(py)
        )
        * resolution
    )

    return x, y


# ============================================================
# PGM -> PNG
# ============================================================

def pgm_to_png_bytes() -> bytes:

    info = load_map_metadata()

    image_path = Path(
        info["image_path"]
    )

    with Image.open(
        image_path
    ) as image:

        converted = image.convert(
            "L"
        )

        output = io.BytesIO()

        converted.save(
            output,
            format="PNG",
        )

        return output.getvalue()