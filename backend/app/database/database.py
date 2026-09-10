import asyncpg
import json
from datetime import datetime

DATABASE_URL = "postgresql://fms_admin:fms_password123@127.0.0.1:5432/fms_db"

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        # 1. 로봇 최신 상태 테이블
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS robots (
                robot_id VARCHAR(50) PRIMARY KEY,
                status VARCHAR(30) DEFAULT 'IDLE',
                battery FLOAT DEFAULT 100.0,
                x FLOAT DEFAULT 0.0,
                y FLOAT DEFAULT 0.0,
                yaw FLOAT DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        # 2. 텔레메트리 히스토리 로그 테이블
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS telemetry_logs (
                id SERIAL PRIMARY KEY,
                robot_id VARCHAR(50) NOT NULL,
                x FLOAT,
                y FLOAT,
                battery FLOAT,
                status VARCHAR(30),
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    print(" -> PostgreSQL FMS 테이블 초기화 완료!")

async def upsert_robot_state(robot_id: str, x: float, y: float, yaw: float, battery: float, status: str):
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO robots (robot_id, x, y, yaw, battery, status, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
            ON CONFLICT (robot_id) DO UPDATE 
            SET x = $2, y = $3, yaw = $4, battery = $5, status = $6, updated_at = CURRENT_TIMESTAMP;
        ''', robot_id, x, y, yaw, battery, status)

        await conn.execute('''
            INSERT INTO telemetry_logs (robot_id, x, y, battery, status)
            VALUES ($1, $2, $3, $4, $5);
        ''', robot_id, x, y, battery, status)

async def get_all_robots():
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT robot_id, status, battery, x, y, yaw, updated_at FROM robots ORDER BY robot_id;')
        return [dict(r) for r in rows]
