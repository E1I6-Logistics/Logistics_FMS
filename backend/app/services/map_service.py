# Map YAML / 이미지 / 좌표 변환

# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# 메모리 기반 이미지 바이트 처리 기능 사용
import io

# 파일 및 디렉터리 경로 처리 기능 사용
from pathlib import Path

# 다양한 타입 정보 표현 기능 사용
from typing import Any

# ROS Map YAML 파일 파싱 기능 사용
import yaml

# Map 이미지 로드 및 변환 기능 사용
from PIL import Image

from ..config import (
    MAP_DIR,
    MAP_YAML_PATH,
)

# ============================================================
# Map Metadata
# ============================================================


# Map YAML 및 이미지 메타데이터 로드 기능
def load_map_metadata() -> dict[str, Any]:

    # Map YAML 파일 존재 여부 확인
    if not MAP_YAML_PATH.exists():

        raise FileNotFoundError(f"Map YAML 파일 없음: {MAP_YAML_PATH}")

    # Map YAML 파일 열기 및 내용 파싱
    with MAP_YAML_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        map_yaml = yaml.safe_load(file)

    # YAML에 정의된 Map 이미지 파일명 사용
    image_name = map_yaml["image"]

    image_path = Path(image_name)

    # 상대 경로인 경우 Map 디렉터리 기준 경로 생성
    if not image_path.is_absolute():
        image_path = MAP_DIR / image_name

    # Map 이미지 파일 존재 여부 확인
    if not image_path.exists():

        raise FileNotFoundError(f"Map 이미지 파일 없음: {image_path}")

    # Map 이미지 크기 정보 확인
    with Image.open(image_path) as image:

        width, height = image.size

    origin = map_yaml["origin"]

    resolution = float(map_yaml["resolution"])

    # Map 메타데이터 사전 생성
    return {
        "yaml_path": str(MAP_YAML_PATH),
        "image_path": str(image_path),
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


# Frontend 공개용 Map 정보 생성 기능
def get_public_map_info() -> dict[str, Any]:

    info = load_map_metadata()

    # 서버 내부 경로는 프론트로 보내지 않음
    # 서버 내부 파일 경로 제거
    info.pop(
        "yaml_path",
        None,
    )

    info.pop(
        "image_path",
        None,
    )

    # Frontend Map 이미지 API 경로 설정
    info["image_url"] = "/api/map/image"

    # Map의 World 좌표 영역 추가
    info["world_bounds"] = get_world_bounds(info)

    return info


# ============================================================
# Map world 영역
# ============================================================


# Map 원점, 해상도, 크기 기준 World 영역 계산 기능
def get_world_bounds(
    map_info: dict[str, Any] | None = None,
) -> dict[str, float]:

    info = map_info or load_map_metadata()

    origin_x = float(info["origin"][0])

    origin_y = float(info["origin"][1])

    resolution = float(info["resolution"])

    width = int(info["width"])

    height = int(info["height"])

    return {
        "min_x": origin_x,
        "min_y": origin_y,
        "max_x": (origin_x + width * resolution),
        "max_y": (origin_y + height * resolution),
    }


# ============================================================
# ROS world 좌표 -> image pixel 좌표
# ============================================================


# ROS World 좌표를 이미지 Pixel 좌표로 변환 기능
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

    origin_x = float(info["origin"][0])

    origin_y = float(info["origin"][1])

    resolution = float(info["resolution"])

    height = float(info["height"])

    px = (float(x) - origin_x) / resolution

    py = height - ((float(y) - origin_y) / resolution)

    return px, py


# ============================================================
# PGM -> PNG
# ============================================================


# PGM Map 이미지를 PNG 바이트 데이터로 변환 기능
def pgm_to_png_bytes() -> bytes:

    info = load_map_metadata()

    image_path = Path(info["image_path"])

    with Image.open(image_path) as image:

        # Map 이미지를 Grayscale 형식으로 변환
        converted = image.convert("L")

        # PNG 결과 저장용 메모리 버퍼 생성
        output = io.BytesIO()

        converted.save(
            output,
            format="PNG",
        )

        return output.getvalue()
