# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# Database 연결 환경변수 사용
import os
# Database 조회 결과 타입 표현 기능 사용
from typing import Any, Optional

# PostgreSQL 비동기 연결 및 Query 처리 기능 사용
import asyncpg


# ============================================================
# PostgreSQL 설정
# ============================================================

# PostgreSQL 연결 주소 설정
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://fms_admin:fms_password123@127.0.0.1:5432/fms_db",
)


# PostgreSQL 연결 Pool 전역 상태 관리
pool: Optional[asyncpg.Pool] = None


# ============================================================
# DB 초기화
# ============================================================

# PostgreSQL 연결 Pool 생성 및 테이블 초기화 기능
async def init_db() -> None:
    # 전역 Database Pool 객체 사용
    global pool

    # 이미 생성된 Pool 존재 시 중복 초기화 방지
    if pool is not None:
        return

    # PostgreSQL 비동기 연결 Pool 생성
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
    )

    # Pool에서 Database 연결 객체 획득
    async with pool.acquire() as conn:

        # ----------------------------------------------------
        # 로봇 최신 상태
        # ----------------------------------------------------

        # Robot 최신 상태 저장 테이블 생성
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS robots (
                robot_id VARCHAR(50) PRIMARY KEY,
                status VARCHAR(30) DEFAULT 'IDLE',
                battery FLOAT DEFAULT 100.0,
                x FLOAT DEFAULT 0.0,
                y FLOAT DEFAULT 0.0,
                yaw FLOAT DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # ----------------------------------------------------
        # Telemetry history
        # ----------------------------------------------------

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_logs (
                id SERIAL PRIMARY KEY,
                robot_id VARCHAR(50) NOT NULL,
                x FLOAT,
                y FLOAT,
                battery FLOAT,
                status VARCHAR(30),
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 조회 성능을 위한 index
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telemetry_logs_robot_time
            ON telemetry_logs (
                robot_id,
                recorded_at DESC
            );
            """
        )

    print(" -> PostgreSQL FMS 테이블 초기화 완료")


# ============================================================
# DB 종료
# ============================================================

# PostgreSQL 연결 Pool 종료 기능
async def close_db() -> None:
    global pool

    if pool is not None:
        # PostgreSQL 연결 Pool 종료
        await pool.close()
        pool = None

        print(" -> PostgreSQL 연결 종료")


# ============================================================
# 로봇 최신 상태 저장
# ============================================================

# Robot 최신 상태 갱신 및 Telemetry 이력 저장 기능
async def upsert_robot_state(
    robot_id: str,
    x: float,
    y: float,
    yaw: float,
    battery: float,
    status: str,
) -> None:

    if pool is None:
        return

    async with pool.acquire() as conn:

        # Robot 상태와 Telemetry 저장을 하나의 Transaction으로 처리
        async with conn.transaction():

            # 최신 상태 갱신
            await conn.execute(
                """
                INSERT INTO robots (
                    robot_id,
                    x,
                    y,
                    yaw,
                    battery,
                    status,
                    updated_at
                )
                VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    $6,
                    CURRENT_TIMESTAMP
                )

                # 동일 Robot ID 존재 시 최신 상태로 갱신
                ON CONFLICT (robot_id)
                DO UPDATE SET
                    x = EXCLUDED.x,
                    y = EXCLUDED.y,
                    yaw = EXCLUDED.yaw,
                    battery = EXCLUDED.battery,
                    status = EXCLUDED.status,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                robot_id,
                x,
                y,
                yaw,
                battery,
                status,
            )

            # telemetry history 저장
            await conn.execute(
                """
                INSERT INTO telemetry_logs (
                    robot_id,
                    x,
                    y,
                    battery,
                    status
                )
                VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5
                );
                """,
                robot_id,
                x,
                y,
                battery,
                status,
            )


# ============================================================
# 전체 로봇 조회
# ============================================================

# 전체 Robot 최신 상태 조회 기능
async def get_all_robots() -> list[dict[str, Any]]:

    if pool is None:
        return []

    async with pool.acquire() as conn:

        # robots 테이블 전체 Robot 상태 조회
        rows = await conn.fetch(
            """
            SELECT
                robot_id,
                status,
                battery,
                x,
                y,
                yaw,
                updated_at
            FROM robots
            ORDER BY robot_id;
            """
        )

        # 조회 결과를 사전 목록으로 변환
        return [
            dict(row)
            for row in rows
        ]


# ============================================================
# 특정 로봇 조회
# ============================================================

# 특정 Robot 최신 상태 조회 기능
async def get_robot(
    robot_id: str,
) -> Optional[dict[str, Any]]:

    if pool is None:
        return None

    async with pool.acquire() as conn:

        # Robot ID 기준 단일 Robot 상태 조회
        row = await conn.fetchrow(
            """
            SELECT
                robot_id,
                status,
                battery,
                x,
                y,
                yaw,
                updated_at
            FROM robots
            WHERE robot_id = $1;
            """,
            robot_id,
        )

        # 조회 결과가 없는 경우 None 반환
        if row is None:
            return None

        # 조회 결과를 사전 형식으로 변환
        return dict(row)