# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a full-stack trading/backtesting system split into independent modules:
- **Backend** (`backend/`): Python Flask API with WebSocket support for real-time trading data streaming
- **Data Pipeline** (`modules/data-pipeline/`): Polygon.io downloader + BigQuery uploader
- **Analysis Toolkit** (`modules/analysis/`): Order utilities, study artifacts, and the canonical dashboard API
- **Dashboard** (`modules/analysis/dashboard/`): canonical React + TypeScript market/study workbench
- **Frontend compatibility** (`modules/frontend/`): npm launcher delegating to the analysis dashboard

## Key Commands

### Backend Development

```bash
# Setup (first time only)
cd Trading-Backtester/backend
./setup.sh

# Start backend server
./start.sh
# OR manually:
source venv/bin/activate
python app.py

# Install new dependencies
pip install <package>
pip freeze > requirements.txt
```

### Frontend Development

```bash
cd Trading-Backtester/modules/analysis/dashboard

# Install dependencies
npm install

# Start development server
npm run dev

# Run linting
npm run lint

# Build for production
npm run build
```

## Architecture Overview

### Backend Architecture

The backend (`/Trading-Backtester/backend/`) implements:

1. **WebSocket Server** - Real-time bidirectional communication
   - Frontend clients join 'frontend' room
   - External scripts join 'script' room
   - Handles CSV data streaming (trades and market data)

2. **REST API** - Stock data retrieval
   - `/stock/<ticker>` endpoints using Polygon.io API
   - Requires POLYGON_API_KEY in the project-root `.env` file

3. **Data Processing**
   - CSV parsing with pandas
   - Pre-trained ML models (v1.joblib, v2.joblib)
   - Custom indicators (Inverse Fisher)

### Dashboard Architecture

The dashboard (`/Trading-Backtester/modules/analysis/dashboard/`) features:
- Catalog-backed local stock and crypto data
- Lightweight Charts v5 price, volume, annotation, and indicator panes
- Versioned `trading-study-run/v1` generator artifacts
- Viewport-sized OHLCV range loading and server aggregation
- TypeScript contract types and URL-restorable state

### WebSocket Data Flow

External scripts send trading data → Backend processes and broadcasts → Frontend displays in real-time

Expected CSV formats are documented in `/backend/README_WEBSOCKETS.md`

## Important Technical Details

1. **CORS Configuration**: Currently allows all origins (`*`) - suitable for development only
2. **Environment Variables**: Sensitive data (API keys) stored in the repo-level `.env`
3. **Debug Mode**: Enabled by default in Flask
4. **No Authentication**: Currently no auth mechanism implemented
5. **Testing**: No formal test framework currently in place

## Development Workflow

1. Backend runs on `http://localhost:5000`
2. Frontend dev server connects to backend WebSocket
3. External scripts can send data via WebSocket using example_script.py as reference
4. Dashboard updates in real-time with trading data

## Key Libraries

**Backend**:
- `vectorbt` - Backtesting framework
- `yfinance` - Yahoo Finance integration
- `flask-socketio` - WebSocket support
- `polygon-api-client` - Market data API

**Frontend**:
- `lightweight-charts` - Financial charting
- `vite` - Build tooling
- React 19 with TypeScript
