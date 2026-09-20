#!/bin/bash

echo "========================================"
echo " FMS Server Stop"
echo "========================================"

# Frontend 종료
if pgrep -f "npm run dev" > /dev/null 2>&1; then
    pkill -f "npm run dev"
    pkill -f "vite"
    echo "[Frontend] STOPPED"
else
    echo "[Frontend] 이미 종료 상태"
fi

# Backend 종료
if pgrep -f "uvicorn backend.app.main:app" > /dev/null 2>&1; then
    pkill -f "uvicorn backend.app.main:app"
    echo "[Backend] STOPPED"
else
    echo "[Backend] 이미 종료 상태"
fi

# Zenoh Bridge 종료
if pgrep -f "zenoh-bridge-ros2dds" > /dev/null 2>&1; then
    pkill -f "zenoh-bridge-ros2dds"
    echo "[Zenoh Bridge] STOPPED"
else
    echo "[Zenoh Bridge] 이미 종료 상태"
fi

# Zenoh Router 종료
if sudo docker ps --format '{{.Names}}' | grep -qx "fms-zenoh-router"; then
    sudo docker stop fms-zenoh-router > /dev/null

    if sudo docker ps --format '{{.Names}}' | grep -qx "fms-zenoh-router"; then
        echo "[Zenoh Router] 종료 실패"
    else
        echo "[Zenoh Router] STOPPED"
    fi
else
    echo "[Zenoh Router] 이미 종료 상태"
fi

echo "========================================"
echo " FMS Stop Complete"
echo "========================================"