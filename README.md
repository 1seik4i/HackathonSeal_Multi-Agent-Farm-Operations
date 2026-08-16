# FarmOps AI

Multi-agent smart agriculture system for monitoring field conditions, coordinating irrigation decisions, and exposing a realtime dashboard for operations.

## Overview

This project combines:

- Node.js + Express backend for REST APIs and WebSocket updates
- React + Vite frontend dashboard for monitoring and controls
- MQTT ingestion for IoT telemetry
- Multi-agent coordination for field analysis, irrigation planning, resource checks, and action verification
- SQLite for local state and optional MongoDB integration for persistent telemetry

## Features

- Sensor telemetry collection from MQTT or REST API
- Data validation and freshness checks
- Device status monitoring per field asset
- Multi-agent decision flow for irrigation and resource planning
- Real-time dashboard with action timeline and telemetry view
- Local demo seeding for testing without hardware

## Architecture

```text
MQTT / REST telemetry
        ↓
IoT ingestion service
        ↓
Data validation & storage
        ↓
Field IoT Agent → Irrigation Agent → Resource Agent → Coordinator
        ↓
Dashboard + WebSocket status updates
```

## Tech Stack

- Backend: Node.js, Express, MQTT.js, SQLite, MongoDB driver
- Frontend: React, Vite
- Runtime: local environment variables and optional Docker Compose

## Repository Structure

```text
client/      React frontend
server/      API, MQTT ingestion, agent orchestration, storage
scripts/     Data simulators and helpers
Dockerfile   Container image for app runtime
compose.yaml Docker Compose setup
README.md    Project overview and setup steps
.env.example Sample environment variables
```

## Quick Start

### 1. Install dependencies

```powershell
npm install
npm --prefix client install
```

### 2. Configure environment

Create a local file named `.env` from the sample:

```powershell
Copy-Item .env.example .env
```

Then fill in your own local values for MQTT broker settings, API keys, and optional MongoDB connection string.

### 3. Run locally

```powershell
npm run dev
```

Open:

- API: http://127.0.0.1:8000
- Frontend: http://127.0.0.1:5173

### 4. Or run with Docker

```powershell
docker compose up --build -d
```

## Environment Variables

The project reads from `.env` for local secrets and runtime config. Do not commit the real `.env` file to GitHub.

Example variables:

- `MQTT_BROKER_HOST`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `API_PORT`
- `GEMINI_API_KEY`
- `GPT_OSS_API_KEY`
- `MONGODB_URI`

## Security Notes

- Keep `.env` local only and never commit real credentials
- Use `.env.example` as the public template with placeholder values
- Ignore generated runtime files such as `.runtime-secrets.json`, `.runtime-settings.json`, and database files
- Rotate any exposed credentials immediately if they were ever committed

## API Examples

```http
POST /api/telemetry
GET /api/telemetry/latest
POST /api/demo/seed
GET /api/health
```

## Demo and Validation

The app supports demo seeding via the dashboard or API to simulate field conditions when real sensor telemetry is unavailable.

## License

This project is intended for internal or educational use unless otherwise specified by the repository owner.
