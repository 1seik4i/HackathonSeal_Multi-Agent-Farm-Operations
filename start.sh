#!/bin/bash
set -euo pipefail

echo "======================================================="
echo "         FARM OPS AI - SMART AGRICULTURE TRACK B       "
echo "======================================================="
echo ""
echo "[1/3] Installing Node.js dependencies..."
npm install
npm --prefix client install

echo ""
echo "[2/3] Building React frontend..."
npm --prefix client run build

echo ""
echo "[3/3] Starting FarmOps AI (Node.js + React)..."
echo "The application will be available at: http://localhost:8000"
echo "======================================================="
node server/app.js
