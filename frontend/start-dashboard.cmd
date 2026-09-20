@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is required. Install Node.js 22.12 or later, then run this file again.
  pause
  exit /b 1
)

node start-dashboard.mjs
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" pause
exit /b %exit_code%