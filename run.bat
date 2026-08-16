@echo off
echo =======================================================
echo          FARM OPS AI - SMART AGRICULTURE TRACK B       
echo =======================================================
echo.
echo [1/2] Installing dependencies...
pip install -r requirements.txt

echo.
echo [2/2] Starting the FarmOps AI Backend ^& Frontend...
echo The application will be available at: http://localhost:8000
echo =======================================================
python -m src.app
