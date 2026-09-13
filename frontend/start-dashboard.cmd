@echo off
chcp 65001 >nul
cd /d "%~dp0"

where node >nul 2>nul
if %errorlevel% neq 0 (
  echo Node.js가 설치되어 있지 않습니다.
  echo https://nodejs.org/ 에서 Node.js 22.12 이상의 LTS 버전을 설치하세요.
  echo 설치 후 이 파일을 다시 실행하세요.
  pause
  exit /b 1
)

where pnpm >nul 2>nul
if %errorlevel% neq 0 (
  echo pnpm이 설치되어 있지 않습니다.
  echo PowerShell에서 npm install --global pnpm 명령을 실행하세요.
  pause
  exit /b 1
)

node start-dashboard.mjs
pause
