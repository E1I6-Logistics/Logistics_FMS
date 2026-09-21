#!/usr/bin/env bash

set -u


# ============================================================
# FMS Main PC Stop Script
#
# Common:
#   - x86_64 Main PC
#   - NVIDIA Jetson aarch64
# ============================================================


echo "========================================"
echo " FMS Server Stop"
echo "========================================"


# ============================================================
# Frontend
# ============================================================

if pgrep -f "vite.*--host" \
    >/dev/null 2>&1 ||
   pgrep -f "npm run dev" \
    >/dev/null 2>&1; then

    pkill -f "npm run dev" \
        2>/dev/null || true

    sleep 1

    pkill -f "vite.*--host" \
        2>/dev/null || true

    echo "[Frontend] STOPPED"

else

    echo "[Frontend] already stopped"

fi


# ============================================================
# Backend
# ============================================================

if pgrep -f "uvicorn backend.app.main:app" \
    >/dev/null 2>&1; then

    pkill -f "uvicorn backend.app.main:app" \
        2>/dev/null || true

    echo "[Backend] STOPPED"

else

    echo "[Backend] already stopped"

fi


# ============================================================
# Zenoh ROS2DDS Bridge
# ============================================================

if pgrep -f "zenoh-bridge-ros2dds" \
    >/dev/null 2>&1; then

    pkill -f "zenoh-bridge-ros2dds" \
        2>/dev/null || true

    echo "[Zenoh Bridge] STOPPED"

else

    echo "[Zenoh Bridge] already stopped"

fi


# ============================================================
# ROS 2 Daemon
# ============================================================

if command -v ros2 >/dev/null 2>&1; then

    ros2 daemon stop \
        >/dev/null 2>&1 || true

fi


# ============================================================
# Zenoh Router
# ============================================================

if command -v docker >/dev/null 2>&1; then

    if sudo docker ps \
        --format '{{.Names}}' \
        | grep -qx "fms-zenoh-router"; then

        sudo docker stop fms-zenoh-router \
            >/dev/null


        if sudo docker ps \
            --format '{{.Names}}' \
            | grep -qx "fms-zenoh-router"; then

            echo "[Zenoh Router] FAILED TO STOP"

        else

            echo "[Zenoh Router] STOPPED"

        fi

    else

        echo "[Zenoh Router] already stopped"

    fi

else

    echo "[Zenoh Router] Docker not found"

fi


echo "========================================"
echo " FMS Stop Complete"
echo "========================================"
