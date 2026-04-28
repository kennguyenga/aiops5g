# 5G AIOps

> **AI-powered operations for a simulated 5G mobile core**

A microservices implementation of a 5G core network with comprehensive failure injection, ML-based anomaly detection, and a Claude-powered SRE agent that can diagnose and remediate issues autonomously.

[![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Claude](https://img.shields.io/badge/Claude-Sonnet_4.5-D97757)](https://www.anthropic.com/claude)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## What this is

A **realistic simulation** of a 5G Standalone (SA) core network running as 7 microservices, plus a full AIOps stack to detect and fix problems:

- **7 Network Functions** — NRF, AUSF, UDM, AMF, SMF, UPF, PCF — each a FastAPI service speaking simplified 3GPP-style messages
- **UPF KPI engine** — realistic data-plane metrics (throughput, packet loss, jitter, bearers per QoS class) that change dynamically with load and faults
- **PCF policy engine** — QoS profiles for voice/video/internet APNs that SMF queries on every PDU session
- **Subscriber simulator** — attach/detach UEs, run sustained churn, watch the AKA flow execute
- **Call flow visualizer** — interactive sequence diagrams of attach/detach, with live trace, history browser, and side-by-side diff mode for failure analysis
- **Failure injection toolkit** — break NFs in 6 different ways at any intensity
- **10 scripted failure scenarios** — multi-step orchestrated chaos (auth-storm, slow-roast, policy-blackhole, cascade-failure, etc.)
- **Telemetry collector** — Prometheus-style metrics + structured JSON logs + W3C trace context propagation
- **ML engine** — Isolation Forest for anomaly detection, Ridge regression for failure prediction
- **LLM SRE agent** — Claude analyzes telemetry and uses tools to remediate failures autonomously

---

## 📚 Documentation

Comprehensive design documents live in [`docs/`](./docs/):

| Document | What it covers | Audience |
|----------|----------------|----------|
| [**HLD**](./docs/HLD.md) | High-Level Design — purpose, principles, components, data flows, quality attributes | Architects, reviewers, hiring managers |
| [**LLD**](./docs/LLD.md) | Low-Level Design — every API endpoint, data model, algorithm, configuration | Engineers implementing/extending |
| [**Architecture**](./docs/ARCHITECTURE.md) | Multiple architectural views with Mermaid + ASCII diagrams | Anyone scanning the repo |
| [**Message Flows**](./docs/MESSAGE_FLOWS.md) | Sequence diagrams for every operation (attach, session, failure injection, scenarios, LLM agent loop, etc.) | 5G engineers, SREs |

GitHub renders Mermaid diagrams natively — open any of these `.md` files in the GitHub UI to see them.

## 📑 Contents

- [Architecture](#-architecture)
- [The 5G Registration Flow](#-the-5g-registration-flow)
- [Failure Catalog](#-failure-catalog)
- [LLM Agent](#-llm-agent)
- [Quick Start (Docker)](#-quick-start-docker)
- [Quick Start (Local)](#-quick-start-local)
- [Deploy to Render.com](#-deploy-to-rendercom)
- [API Reference](#-api-reference)
- [Project Layout](#-project-layout)

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                FRONTEND  ·  React + Vite + Tailwind                 │
│                          Port 5173 (dev) / 80 (docker)              │
├─────────────────────────────────────────────────────────────────────┤
│  Topology · Subscribers · Failures · Telemetry · ML · Agent         │
└──┬──────────────────────────────────────────────────────────────┬───┘
   │                                                              │
   │  /api/orchestrator/*       /api/collector/*                  │
   │  /api/ml/*                 /api/llm/*                        │
   ▼                                                              ▼
┌──────────────────────┐    ┌─────────────────────┐    ┌──────────────┐
│  ORCHESTRATOR  :9001 │    │  COLLECTOR    :9000 │    │  ML   :9002  │
│  • subscriber sim    │    │  • scrape /metrics  │    │  Isolation   │
│  • chaos injection   │    │  • scrape /logs     │    │  Forest +    │
│  • topology API      │    │  • scrape /traces   │    │  Ridge       │
└──┬──────────────────┬┘    │  • aggregation API  │    └──────┬───────┘
   │                  │     └─────┬───────────────┘           │
   │ HTTP             │           │                           │
   ▼                  ▼           │      ┌────────────────────┘
┌─────────────────────────────────┐│      │
│        5G CORE NFs (7)          ││      │   ┌─────────────────────┐
│                                 │└──────┴─→ │  LLM AGENT   :9003  │
│  ┌──────┐  ┌──────┐  ┌──────┐   │          │  Claude classifier  │
│  │ NRF  │  │ AUSF │  │ UDM  │   │          │  + tool-using agent │
│  │:8001 │  │:8002 │  │:8003 │   │          │                     │
│  └──────┘  └──────┘  └──────┘   │          │  Tools:             │
│  ┌──────┐  ┌──────┐  ┌──────┐   │          │   read_logs         │
│  │ AMF  │  │ SMF  │  │ UPF  │   │          │   query_metrics     │
│  │:8004 │  │:8005 │  │:8006 │   │          │   get_topology      │
│  └──────┘  └──────┘  └──────┘   │          │   list_failures     │
│  ┌──────┐  ←── KPI engine ──↑   │          │   clear_failure     │
│  │ PCF  │  (throughput, loss,   │          │                     │
│  │:8007 │   jitter, bearers)    │          └─────────────────────┘
│  └──────┘                       │
└─────────────────────────────────┘
   ▲                  ▲
   │ /failure         │ /failure
   │ injection        │  + 10 scripted scenarios
   └──── chaos ───────┘    (auth-storm, slow-roast, ...)
```

---

## 🔄 The 5G Registration Flow

When a UE attaches, here's what happens across the NFs:

```
UE                AMF              AUSF              UDM
 │  REGISTER      │                 │                 │
 │ ────────────→  │                 │                 │
 │                │  /auth/init     │                 │
 │                │ ──────────────→ │                 │
 │                │                 │  /subscribers/  │
 │                │                 │  {supi}/        │
 │                │                 │  auth-vector    │
 │                │                 │ ──────────────→ │
 │                │                 │                 │
 │                │                 │ ←── (RAND,XRES, │
 │                │                 │      AUTN) ──── │
 │  RAND, AUTN    │                 │                 │
 │ ←──────────────│ ←── challenge ──│                 │
 │                │                 │                 │
 │  RES (computed │                 │                 │
 │  by toy        │                 │                 │
 │  MILENAGE)     │                 │                 │
 │ ────────────→  │  /auth/confirm  │                 │
 │                │ ──────────────→ │                 │
 │                │                 │  compare        │
 │                │                 │  RES vs XRES    │
 │                │ ←── ok ─────────│                 │
 │                │                 │                 │
 │                │  /subscribers/  │                 │
 │                │  {supi}/profile │                 │
 │                │ ──────────────────────────────→   │
 │                │ ←──── (NSSAI, APN, PLMN) ─────    │
 │  REGISTERED    │                                   │
 │ ←──────────────│                                   │
                  │
                  │  Then: /sessions to SMF for PDU establishment
```

Every step emits structured JSON logs with trace context, so when something fails the LLM agent can trace the failure through the system.

---

## ⚡ 5G Error Codes & ML Pattern Classifier

The system implements **25 standard 5G cause codes** per 3GPP TS 29.500 (SBI HTTP problem+json) and TS 24.501 (NAS 5GMM/5GSM cause values). NFs emit these as proper `application/problem+json` responses with HTTP status, NAS cause number, cause name, and detail.

**Two ways failures emerge:**

1. **NF-level injection** (Failures tab → "5G Coded Error" type): pick any combination of codes the target NF can emit, set the rate. Middleware applies them to incoming requests.

2. **Subscriber-level state** (ErrorCodes tab → Subscriber State): each subscriber in UDM has a state. Non-ACTIVE states cause UDM to return specific 5G codes when AMF/AUSF look them up:

   | State | Cause emitted |
   |-------|---------------|
   | `BLOCKED` | `ILLEGAL_UE` |
   | `ROAMING_NOT_ALLOWED` | `ROAMING_NOT_ALLOWED` |
   | `AUTH_KEY_REVOKED` | `UE_AUTH_KEY_REVOKED` |
   | `SUSPENDED` | `USER_NOT_ALLOWED` |
   | `PROVISIONING_PENDING` | `SUBSCRIPTION_NOT_FOUND` |

   States are **persistent within the session** — a subscriber stays BLOCKED until you explicitly reset.

**ML pattern classifier** (`POST /api/ml/classify-failure`, surfaced in ErrorCodes tab):
- Pattern matches the live error-code distribution against a knowledge base of 8 known scenarios
- Returns ranked diagnoses with match scores (0-1) and 3-5 ranked remediation suggestions
- **Recommend-only** — never auto-executes. The LLM agent or operator decides what to apply.

**LLM agent enhancements:**
- 4 new tools: `query_error_codes`, `query_subscriber_states`, `reset_subscribers`, `classify_failure`
- System prompt teaches Claude all 25 codes with category groupings and diagnosis heuristics
- Total of 9 tools available in the autonomous remediation loop

**6 new code-aware scenarios** (16 total now): `auth-reject-storm`, `dnn-mismatch`, `congestion-cascade`, `roaming-restriction`, `slice-capacity-exhausted`, `subscription-kaleidoscope`.

## ⇄ Call Flow Visualizer

Interactive sequence diagrams of subscriber lifecycle events. Three modes:

**Live trace** — pick a SUPI (or random), choose a flow type (attach / attach+session / detach), click trace. The orchestrator runs the flow with a known trace_id, then polls the collector for the resulting spans and renders them as an SVG sequence diagram with arrows between NF lanes, operation names, and per-call latency annotations.

**History browser** — table of all recent traces from the collector's span buffer, filterable by SUPI. Click any row to render its sequence diagram. Useful for "this UE failed an hour ago — what happened?"

**Diff mode** — pick any two traces from dropdowns, render side by side. The dropdown labels include status (✓/✗) and duration so you can quickly find a successful vs failed pair to compare.

The diagram colors arrows by direction and outcome:
- **Phosphor green** — outbound request
- **Amber dashed** — return response
- **Red** — error response

Trigger a `policy-blackhole` scenario then trace an attach — you'll literally see the SMF→PCF arrow turn red and the flow halt there. Then run the LLM Agent and Claude can use the trace data to ground its diagnosis.

## 🎬 Scenario Library

Scripted multi-step failure scenarios that combine fault injection with UE load to create realistic patterns. Each scenario emits structured log markers so the LLM agent's diagnoses can be benchmarked against ground truth.

| Scenario | Severity | Duration | What it does |
|----------|----------|----------|--------------|
| `auth-storm` | high | 30s | UDM throttled while 50 UEs attach simultaneously |
| `slow-roast` | medium | 70s | AUSF latency ramps gradually 100ms → 5000ms |
| `silent-udm` | medium | 65s | UDM returns 500 to ~15% of requests — easy to miss |
| `pdu-collapse` | high | 30s | SMF unhealthy — registered UEs OK, no new sessions |
| `upf-overload` | medium | 45s | UPF packet corruption climbs as bearers accumulate |
| `policy-blackhole` | critical | 25s | PCF blackholes — PDU sessions stuck PENDING |
| `cascade-failure` | critical | 50s | NRF slow — service discovery degrades, multi-NF symptoms |
| `auth-then-recover` | medium | 55s | AUSF errors 30s then auto-recovers (test resolved-issue detection) |
| `flash-crowd` | low | 20s | 200 UEs attach in 10s — pure capacity test, no faults |
| `byzantine-pcf` | medium | 30s | PCF returns mangled responses — subtle, hard to detect |

Trigger any scenario from the **Scenarios** tab in the UI, or via API:
```bash
curl -X POST http://localhost:19001/api/scenarios/policy-blackhole/run
```

Then click the **LLM Agent** tab and start the autonomous agent — Claude will use its tools (`list_failures`, `read_logs`, `query_metrics`, `clear_failure`) to investigate and remediate.

## 🚨 Failure Catalog

The orchestrator exposes 6 failure presets that can target any NF at any intensity (0.1 = mild, 1.0 = severe):

| Preset | Effect |
|--------|--------|
| `nf_crash` | NF returns 503, hangs all requests, marks unhealthy |
| `nf_slowdown` | Adds `intensity × 2000ms` latency to every request |
| `nf_error_rate` | NF returns 500s with probability = intensity |
| `nf_unhealthy` | `/healthz` fails but service still responds |
| `packet_corruption` | Returns mangled responses |
| `intermittent` | Lower error rate (intensity × 0.3) — harder to detect |

Each NF has a `/failure` endpoint that the orchestrator pokes to set the fault config. The middleware reads this config on every request.

---

## 🧠 LLM Agent

Two modes:

### Classifier mode — single-shot diagnosis
- Reads telemetry summary + failure injection state
- Returns structured JSON: root cause, affected NF, severity, evidence, recommended actions, confidence

### Agent mode — autonomous tool-using loop
- Up to 8 iterations of: think → call tool → observe → repeat
- Tools: `read_logs`, `query_metrics`, `get_topology`, `list_failures`, `clear_failure`
- Stops when Claude is confident issue is resolved (no more tool calls)
- Returns full transcript so you can see Claude's reasoning step-by-step

Powered by `claude-sonnet-4-5` via the Anthropic API. You provide your own API key.

---

## 🐳 Quick Start (Docker)

```bash
# 1. Set your Anthropic API key (optional but needed for the LLM tab)
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Build and run everything
docker compose up --build

# 3. Open http://localhost:5173
```

What you should see (suggested order to explore):

1. **Topology** — wait ~10s for all NFs to register, then see them all green
2. **Subscribers → Attach 10 UEs** — watch the registration flow execute, then go back to Topology to see request counts spike
3. **Failures → inject `nf_slowdown` on AMF at intensity 0.5** — return to Topology, see latency climb
4. **Subscribers → Start Load** — watch errors accumulate in real time
5. **Telemetry** — see the structured logs streaming in
6. **ML → Scan All NFs** — Isolation Forest flags AMF as anomalous
7. **Agent → Start Agent** — Claude investigates and clears the fault. Read the transcript to see its reasoning.

---

## 💻 Quick Start (Local — No Docker)

If you don't have Docker, run each service in its own terminal:

```bash
# Backend setup (once)
cd services
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Then in 9 separate terminals:
NRF_URL=http://localhost:8001 AUSF_URL=http://localhost:8002 UDM_URL=http://localhost:8003 \
AMF_URL=http://localhost:8004 SMF_URL=http://localhost:8005 \
COLLECTOR_URL=http://localhost:9000 ORCHESTRATOR_URL=http://localhost:9001 \
ANTHROPIC_API_KEY=sk-ant-... \
uvicorn nrf.main:app --port 8001          # Terminal 1
uvicorn udm.main:app --port 8003          # Terminal 2
uvicorn ausf.main:app --port 8002         # Terminal 3
uvicorn amf.main:app --port 8004          # Terminal 4
uvicorn smf.main:app --port 8005          # Terminal 5
uvicorn collector.main:app --port 9000    # Terminal 6
uvicorn orchestrator.main:app --port 9001 # Terminal 7
uvicorn ml_engine.main:app --port 9002    # Terminal 8
uvicorn llm_agent.main:app --port 9003    # Terminal 9

# Frontend (Terminal 10)
cd frontend
npm install && npm run dev
```

Open http://localhost:5173

---

## ☁️ Deploy to Render.com

This repo includes a `render.yaml` Blueprint. **Heads up**: deploying 9 microservices on Render's free tier means cold-starts will be brutal. For a smooth demo, consider Starter plan.

```bash
git push origin main
# Then: Render Dashboard → New + → Blueprint → select repo
```

After provisioning, set `ANTHROPIC_API_KEY` in the dashboard for the `aiops5g-llm-agent` service. The frontend's `VITE_API_BASE` will need manual configuration to point at the deployed service URLs (or use a single domain with subpaths via a load balancer).

For deployment details, see [DEPLOY.md](./DEPLOY.md).

---

## 📡 API Reference

### Orchestrator (`:9001`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/subscribers/attach` | Attach N UEs |
| POST | `/api/subscribers/detach` | Detach UEs |
| POST | `/api/subscribers/load` | Start sustained churn |
| POST | `/api/subscribers/load/stop` | Stop load |
| POST | `/api/failures/inject` | Inject failure on NF |
| POST | `/api/failures/clear` | Clear failures |
| GET  | `/api/failures/state` | Current failure state per NF |
| GET  | `/api/topology` | NF topology + health |

### Collector (`:9000`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/nfs/status` | Per-NF up/down |
| GET | `/api/metrics/{nf}` | Metric history (300s window) |
| GET | `/api/metrics/{nf}/series/{name}` | Time-series of one metric |
| GET | `/api/logs` | Unified log search (filter by nf, level, supi, since) |
| GET | `/api/traces` | Spans by trace_id |
| GET | `/api/summary` | High-level state summary |

### ML Engine (`:9002`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/ml/anomalies` | Isolation Forest scan across NFs |
| POST | `/api/ml/forecast?nf=&metric=` | Ridge forecast 15min ahead |

### LLM Agent (`:9003`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/llm/diagnose` | Single-shot Claude analysis |
| POST | `/api/llm/remediate` | Tool-using agent loop |

### NF Endpoints (each NF, ports 8001–8005)
- `GET /healthz` — health check
- `GET /metrics` — Prometheus-style metric snapshot
- `GET /logs` — recent JSON log entries
- `GET /traces` — spans
- `GET/POST /failure` — fault config

Full Swagger UI per NF at `http://localhost:PORT/docs`.

---

## 📁 Project Layout

```
aiops5g/
├── README.md                    This file
├── docker-compose.yml           Full stack — single command to run
├── Dockerfile                   Single image for all Python services
├── render.yaml                  Render blueprint
│
├── services/
│   ├── requirements.txt
│   ├── nf_common/__init__.py    Shared library (telemetry, models, base app)
│   ├── nrf/main.py              Service registry
│   ├── udm/main.py              Subscriber DB + AKA crypto (1000 pre-provisioned)
│   ├── ausf/main.py             Auth challenge/response
│   ├── amf/main.py              UE registration entry point
│   ├── smf/main.py              PDU session manager
│   ├── collector/main.py        Telemetry aggregator
│   ├── orchestrator/main.py     Subscriber sim + failure injection
│   ├── ml_engine/main.py        Isolation Forest + Ridge
│   └── llm_agent/main.py        Claude classifier + agent
│
└── frontend/
    ├── Dockerfile               Multi-stage → nginx
    ├── nginx.conf               Serves SPA + proxies /api to services
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    └── src/
        ├── App.jsx
        ├── api.js
        ├── main.jsx
        ├── index.css
        └── components/
            ├── Topology.jsx     Animated SVG mesh, health colors
            ├── Subscribers.jsx  UE attach/detach + load gen
            ├── Failures.jsx     Chaos injection panel
            ├── Telemetry.jsx    Live log stream
            ├── MLView.jsx       Anomaly results + forecast charts
            ├── Agent.jsx        Diagnose + remediate transcript view
            └── ui.jsx           Shared primitives
```

---

## ⚠️ This is a simulation, not a 5G core

The crypto is a toy SHA-256 — **never use this for security**. The NFs implement simplified versions of 3GPP TS 29.500-series APIs. UPF is stubbed (no real GTP-U). PCF is omitted. There's no real RAN, no NAS messaging, no NGAP. The point is to demonstrate **AIOps patterns on a system that looks and feels like a 5G core**, not to be a 5G core.

---

## 📜 License

Ken Nguyen
@2026

---

<div align="center">

**Built with FastAPI, React, scikit-learn, Claude, and a healthy disrespect for protocol compliance.**

</div>
