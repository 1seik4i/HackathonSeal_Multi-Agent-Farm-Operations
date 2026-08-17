@echo off
echo =======================================================
echo          FARM OPS AI - SMART AGRICULTURE TRACK B
echo =======================================================
echo.
echo [1/3] Installing Node.js dependencies...
call npm install
call npm --prefix client install

echo.
echo [2/3] Building React frontend...
call npm --prefix client run build

echo.
echo [3/3] Starting FarmOps AI Node.js Backend + React Frontend...
echo The application will be available at: http://localhost:8000
echo =======================================================
node server/app.js
