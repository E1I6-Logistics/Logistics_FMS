import asyncio
import zenoh
import asyncpg

async def test_infrastructure():
    print("[1/2] Zenoh 라우터 연결 확인 중...")
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
    session = zenoh.open(conf)
    print(f" -> Zenoh 연결 성공! (Router ZID: {session.zid()})")

    print("\n[2/2] PostgreSQL 데이터베이스 연결 확인 중...")
    conn = await asyncpg.connect(
        user='fms_admin',
        password='fms_password123',
        database='fms_db',
        host='127.0.0.1',
        port=5432
    )
    db_version = await conn.fetchval('SELECT version();')
    print(f" -> DB 연결 성공!\n    ({db_version.split(',')[0]})")
    await conn.close()
    session.close()

if __name__ == "__main__":
    asyncio.run(test_infrastructure())