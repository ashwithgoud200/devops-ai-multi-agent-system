# DevOps dashboard

The React/Vite dashboard reads live data from the existing FastAPI application. The Vite development server binds to loopback and proxies API, Prometheus, Grafana, and Ollama requests, so no backend CORS or workflow changes are required.

## Run locally

Start the API from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn calculator_app.app:app --host 127.0.0.1 --port 8100
```

In another PowerShell terminal:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://127.0.0.1:5173`). Start the Prometheus, Grafana, and Ollama services separately when their live status or telemetry is needed. The dashboard identifies unavailable services and telemetry rather than substituting sample values.

## Build

```powershell
Set-Location .\frontend
npm run build
```

The dashboard does not approve remediation automatically. An operator must review the proposal and explicitly confirm approval before the existing workflow can execute rollback.
