# Low-Level Design (LLD) — 5G AIOps

**Document Status:** Draft v1.0
**Audience:** Engineers implementing or extending the system
**Scope:** All APIs, data models, algorithms, internal contracts

---

## 1. Repository Structure

```
aiops5g/
├── docker-compose.yml         # Orchestration of 10 services
├── Dockerfile                 # Single Python image, parameterized by SERVICE_NAME
├── render.yaml                # Cloud deployment blueprint
├── clean-rebuild.ps1          # Windows helper script
│
├── docs/                      # ⟵ this folder
│   ├── HLD.md
│   ├── LLD.md
│   ├── ARCHITECTURE.md
│   └── MESSAGE_FLOWS.md
│
├── services/
│   ├── requirements.txt       # All Python deps for all NFs (intentionally shared)
│   ├── nf_common/             # Shared library — see §3
│   │   └── __init__.py
│   ├── nrf/main.py            # NRF — service registry
│   ├── ausf/main.py           # AUSF — auth
│   ├── udm/main.py            # UDM — subscriber DB
│   ├── amf/main.py            # AMF — access entry point
│   ├── smf/main.py            # SMF — session manager
│   ├── upf/main.py            # UPF — user plane + KPI engine
│   ├── pcf/main.py            # PCF — policy control
│   ├── collector/main.py      # Telemetry aggregator
│   ├── orchestrator/
│   │   ├── main.py            # Subscriber sim + failure injection
│   │   └── scenarios.py       # 10 scripted scenarios
│   ├── ml_engine/main.py      # Isolation Forest + Ridge regression
│   └── llm_agent/main.py      # Claude classifier + agent
│
└── frontend/
    ├── Dockerfile             # Multi-stage → nginx
    ├── nginx.conf             # SPA + reverse-proxy config
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    └── src/
        ├── App.jsx            # Top-level layout + routing
        ├── api.js             # Centralized API client
        └── components/
            ├── ui.jsx          # Shared primitives (Panel, Button, Tag, etc.)
            ├── Topology.jsx
            ├── Subscribers.jsx
            ├── CallFlow.jsx    # Sequence diagram visualizer
            ├── Failures.jsx
            ├── Scenarios.jsx
            ├── Telemetry.jsx
            ├── MLView.jsx
            └── Agent.jsx
```

---

## 2. Single-Image, Multi-Service Pattern

The Dockerfile builds **one image** that all 11 Python services use. Per-service behavior is selected by env vars at run time.

**Dockerfile** (excerpt):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services /app/services
WORKDIR /app/services
CMD uvicorn ${SERVICE_NAME}.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

**docker-compose.yml** sets `SERVICE_NAME` and `PORT` per service:
```yaml
nrf:
  build: .
  environment: { SERVICE_NAME: nrf, PORT: 8001 }
  ports: ["18001:8001"]
```

**Tradeoffs:**
- ✅ Single image build — much faster CI/CD
- ✅ One requirements.txt to maintain
- ❌ All services bring all dependencies (e.g. NRF includes scikit-learn). For an experimental project this is fine; for prod you'd want service-specific images.

---

## 3. The `nf_common` Shared Library

`services/nf_common/__init__.py` provides everything every NF needs:

### 3.1 Telemetry class

```python
class Telemetry:
    """In-memory metrics + logs + traces."""

    def __init__(self, nf: str):
        self.nf = nf
        self.counters: dict[str, float] = defaultdict(float)
        self.gauges: dict[str, float] = {}
        self.histograms: dict[str, list[float]] = defaultdict(list)
        self.logs: deque = deque(maxlen=2000)
        self.spans: deque = deque(maxlen=1000)

    def inc(self, name: str, **labels): ...      # counter increment
    def gauge(self, name: str, value: float): ...
    def histogram(self, name: str, value: float): ...
    def info(self, msg: str, **kw): ...           # log
    def warn(self, msg: str, **kw): ...
    def error(self, msg: str, **kw): ...

    @asynccontextmanager
    async def span(self, op: str, trace_id: str = None,
                   parent_span_id: str = None, **attrs):
        """Records an OpenTelemetry-style span with timing + status."""
        ...
```

### 3.2 NFClient — the inter-NF HTTP client

Wraps httpx with automatic trace propagation:

```python
class NFClient:
    """HTTP client for inter-NF calls. Adds:
       - automatic span recording (call_<target>_<path>)
       - W3C trace context (X-Trace-Id, X-Parent-Span-Id headers)
       - error classification → metrics + logs
       - timeout handling
    """
    async def call(self, target_nf: str, method: str, path: str,
                   json: dict = None, trace_id: str = None,
                   parent_span_id: str = None) -> dict:
        ...
```

### 3.3 Failure Injection Middleware

Every NF gets the same middleware that reads its `/failure` config and applies the chaos:

```python
class FailureConfig(BaseModel):
    error_rate: float = 0.0       # 0.0 to 1.0 — return 500 with this probability
    extra_latency_ms: int = 0     # added to every request
    blackhole: bool = False       # hang the request indefinitely
    corruption_rate: float = 0.0  # return mangled responses
    unhealthy: bool = False       # /healthz returns 503
```

Middleware flow:
1. Sleep `extra_latency_ms` if set
2. If `blackhole`: hang for 30s then 503
3. If `random.random() < error_rate`: return 500
4. If `random.random() < corruption_rate`: scramble response body
5. Otherwise: pass through

### 3.4 Shared Pydantic models

```python
class Subscriber(BaseModel):
    supi: str           # e.g. "imsi-001010000000001"
    plmn: str           # "00101"
    auth_key: str       # 32 hex chars (toy crypto)
    apn_list: list[str] # e.g. ["internet", "ims"]
    nssai: list[str]    # network slice IDs
    state: str          # "PROVISIONED" | "ACTIVE"

class UE(BaseModel):
    supi: str
    amf_ue_id: str
    state: str          # "REGISTERING" | "REGISTERED" | "DEREGISTERING" | "DEREGISTERED"
    plmn: str
    pdu_sessions: list[str]
    last_activity: float

class PDUSession(BaseModel):
    pdu_id: str
    supi: str
    apn: str
    state: str          # "PENDING" | "ACTIVE" | "FAILED" | "RELEASED"
    qos_flow: str       # "5qi-1" | "5qi-5" | "5qi-9"
    upf_assigned: Optional[str]
    bearer_id: Optional[str]
```

### 3.5 The `create_nf_app` factory

Every NF starts with this one line:
```python
app, tel, failure = create_nf_app("smf", 8005)
```

It wires up FastAPI + telemetry + failure middleware + standard endpoints (`/healthz`, `/metrics`, `/logs`, `/traces`, `/failure`) so each NF only writes its own business logic.

---

## 4. Per-NF API Reference

Every NF exposes these standard endpoints (provided by `nf_common`):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/healthz` | GET | Health check — returns `{status, nf}` or 503 if `failure.unhealthy` |
| `/metrics` | GET | Snapshot of counters/gauges/histograms |
| `/logs?since=&level=&supi=` | GET | Recent log entries with filters |
| `/traces?trace_id=` | GET | Recent spans, filtered by trace_id if given |
| `/failure` | GET/POST | Read/write the failure config |

Plus the NF-specific endpoints below.

### 4.1 NRF — Network Repository Function

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/services/register` | POST | `{nf_type, nf_instance_id, ip_endpoint}` → `{registered: bool}` |
| `/services/{nf_type}` | GET | List of `ServiceInstance` for given type |
| `/services/{nf_type}/{nf_instance_id}` | DELETE | Deregister one instance |

**State**: `services_registered: dict[str, list[ServiceInstance]]`

### 4.2 AUSF — Authentication Server

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/auth/init` | POST | `{supi}` → `{rand, autn, ausf_session_id}` |
| `/auth/confirm` | POST | `{supi, ausf_session_id, res}` → `{authenticated: bool}` |

**Algorithm** (toy AKA):
```
1. AMF calls /auth/init with SUPI
2. AUSF calls UDM /subscribers/{supi}/auth-vector to get (RAND, XRES, AUTN)
3. AUSF stores (XRES, ausf_session_id) in memory, returns (RAND, AUTN) to AMF
4. AMF gives RAND/AUTN to UE; UE computes RES = SHA256(K || RAND)[:8]
5. UE sends RES back to AMF, AMF calls /auth/confirm
6. AUSF compares RES vs XRES → authenticated true/false
```

### 4.3 UDM — Unified Data Management

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/subscribers/{supi}` | GET | Full Subscriber object |
| `/subscribers/{supi}/auth-vector` | GET | `{rand, xres, autn}` (RAND is fresh each call) |
| `/subscribers/{supi}/profile` | GET | `{nssai, apn_list, plmn}` |
| `/subscribers` | GET | `{total, sample: [...]}` (1000 pre-provisioned) |

**State**: `subscribers: dict[supi, Subscriber]` — provisioned at startup with deterministic auth keys (`f"{i:032x}"` for i=1..1000).

### 4.4 AMF — Access & Mobility

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/ue/register` | POST | `{supi, plmn, ue_auth_key}` → `{status, supi, amf_ue_id, profile, trace_id}` |
| `/ue/session` | POST | `{supi, apn}` → PDU session object + `trace_id` |
| `/ue/deregister` | POST | `{supi}` → `{status, trace_id}` |
| `/ue/{supi}` | GET | UE state |
| `/ue` | GET | List active UEs |

Accepts `X-Trace-Id` header for externally-correlated traces.

### 4.5 SMF — Session Management

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/sessions` | POST | `{supi, apn}` → PDUSession |
| `/sessions/{pdu_id}` | DELETE | Release session |
| `/sessions` | GET | `{total, by_state, sessions}` |

**Internal flow on POST /sessions:**
1. PCF policy decision (5qi, max bandwidth, charging rule)
2. UPF bearer install (returns bearer_id)
3. Update session.state = ACTIVE
4. On any failure → state = FAILED, attempt cleanup

### 4.6 UPF — User Plane

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/bearers` | POST | `{pdu_id, supi, qos_5qi}` → `Bearer` |
| `/bearers/{bearer_id}` | DELETE | Release bearer |
| `/bearers?state=ACTIVE` | GET | List bearers |
| `/kpi` | GET | Live KPI snapshot |

**KPI Engine**: Background asyncio task (1s tick) updates gauges based on:
- Per-bearer throughput by 5QI (1=0.1Mbps voice, 5=5Mbps video, 9=2Mbps internet)
- Random ±20% jitter per bearer
- Packet loss = base (0.01% per bearer) + corruption_rate × 100
- Jitter = 2.0 + loss × 5 + random
- N3/N6 throughput totals

### 4.7 PCF — Policy Control

| Endpoint | Method | Body / Returns |
|----------|--------|----------------|
| `/policies/decide` | POST | `{supi, apn}` → policy with `{qos_5qi, max_dl_mbps, max_ul_mbps, priority_level, charging_rule}` |
| `/policies/{supi}` | GET / DELETE | Get / revoke active policy |
| `/policies` | GET | List active policies + count by APN |

**Policy templates** (hard-coded by APN):
| APN | 5QI | Max DL | Max UL | Priority |
|-----|-----|--------|--------|----------|
| internet | 9 | 100 Mbps | 50 Mbps | 8 |
| voice | 1 | 0.1 Mbps | 0.1 Mbps | 2 |
| video | 5 | 25 Mbps | 10 Mbps | 4 |

---

## 5. Control Plane API Reference

### 5.1 Collector — `:9000`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/nfs/status` | GET | `{nf: {up: bool, last_seen: float}}` for all NFs |
| `/api/metrics/{nf}` | GET | Last 300s of metric snapshots |
| `/api/metrics/{nf}/series/{name}?since=` | GET | Time-series of one metric |
| `/api/logs?nf=&level=&supi=&since=&limit=` | GET | Unified log search |
| `/api/traces?trace_id=&limit=` | GET | Spans, filtered by trace_id if given |
| `/api/traces/recent?supi=&limit=` | GET | Per-trace summaries (groups spans by trace_id) |
| `/api/summary` | GET | High-level state: per-NF up/down + key counters |

**Scrape loop** (every 5s):
```python
for nf in NF_TYPES:
    try:
        m = await client.get(f"{nf_url}/metrics", timeout=3)
        l = await client.get(f"{nf_url}/logs", timeout=3)
        t = await client.get(f"{nf_url}/traces", timeout=3)
        state.METRIC_HISTORY[nf].append((time.time(), m.json()))
        state.LOGS[nf].extend(l.json()["logs"])
        state.SPANS.extend(t.json()["spans"])
        state.LAST_SEEN[nf] = time.time()
    except Exception:
        pass  # NF unreachable — don't update LAST_SEEN
```

### 5.2 Orchestrator — `:9001`

| Endpoint | Method | Body | Purpose |
|----------|--------|------|---------|
| `/api/subscribers/attach` | POST | `{count, parallelism}` | Attach N UEs |
| `/api/subscribers/detach` | POST | `{count}` | Detach N currently-attached |
| `/api/subscribers/load` | POST | `{attach_rate, detach_rate, duration_s, max_active}` | Sustained churn |
| `/api/subscribers/load/stop` | POST | – | Stop load |
| `/api/subscribers/state` | GET | – | Active SUPI list, counts |
| `/api/failures/inject` | POST | `{nf, error_rate, extra_latency_ms, ...}` | Push fault config to NF |
| `/api/failures/clear` | POST | `?nf=` | Clear fault on one or all NFs |
| `/api/failures/state` | GET | – | Current fault config of every NF |
| `/api/topology` | GET | – | NF list + edges + health |
| `/api/scenarios` | GET | – | List of 10 scenarios |
| `/api/scenarios/{id}/run` | POST | – | Start scenario |
| `/api/scenarios/stop` | POST | – | Cancel running scenario |
| `/api/scenarios/state` | GET | – | Live transcript |
| `/api/scenarios/history` | GET | `?limit=` | Past runs with full logs |
| `/api/callflow/trace` | POST | `{supi?, flow, apn?}` | Run attach/detach with known trace_id |

### 5.3 ML Engine — `:9002`

| Endpoint | Method | Body | Purpose |
|----------|--------|------|---------|
| `/api/ml/anomalies` | POST | `{nf?}` (omit for all) | Run Isolation Forest |
| `/api/ml/forecast` | POST | `?nf=&metric=` | Ridge regression — 15min horizon |

**Anomaly detection algorithm**:
```python
samples = collector.metrics(nf).last(300s)
features = [(req_rate, err_rate, p99_latency)
            for window in samples.window(30s)]
model = IsolationForest(n_estimators=100, contamination='auto')
scores = model.fit_predict(features)
anomalies = [s for s, score in zip(samples, scores) if score == -1]
return {nf, samples: len(samples), anomalies, anomaly_count, anomaly_rate}
```

**Forecast algorithm**:
```python
samples = collector.metrics(nf).series(metric).last(1h)
X = features(timestamp) + [hour_sin, hour_cos]   # cyclic time
y = values
model = Ridge(alpha=1.0).fit(X, y)
forecast = model.predict(X_future_15min)
ci = 1.96 * residual_std
return {forecast: [(t, predicted, lower, upper)], fit_quality: {mae, rmse}}
```

### 5.4 LLM Agent — `:9003`

| Endpoint | Method | Body | Purpose |
|----------|--------|------|---------|
| `/api/llm/diagnose` | POST | – | Single-shot Claude diagnosis |
| `/api/llm/remediate` | POST | `{goal, max_iterations}` | Tool-using agent loop |

**Tools available to the agent**:
```python
TOOLS = [
    {
        "name": "read_logs",
        "description": "Read recent logs from a specific NF",
        "input_schema": {
            "type": "object",
            "properties": {
                "nf": {"type": "string", "enum": ["amf", "smf", "ausf", "udm", "nrf", "upf", "pcf", "all"]},
                "level": {"type": "string", "enum": ["info", "warn", "error", "any"]},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_metrics",
        "description": "Get current metrics for an NF",
        "input_schema": {...},
    },
    {
        "name": "get_topology",
        "description": "Get NF topology and health status",
        "input_schema": {...},
    },
    {
        "name": "list_failures",
        "description": "List currently-injected failures across all NFs",
        "input_schema": {...},
    },
    {
        "name": "clear_failure",
        "description": "Clear injected failure on a specific NF",
        "input_schema": {...},
    },
]
```

**Agent loop** (simplified):
```python
messages = [{"role": "user", "content": goal}]
for i in range(max_iterations):
    response = anthropic.messages.create(
        model=CLAUDE_MODEL,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=TOOLS,
    )
    if response.stop_reason != "tool_use":
        break  # agent is done
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            result = call_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result)[:5000],
            })
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})
```

---

## 6. Telemetry Internals

### 6.1 Span structure

```json
{
  "trace_id": "f7c2e8b9d4a1...",
  "span_id": "8a3c5f7d",
  "parent_span_id": "1a2b3c4d",      // null for root spans
  "operation": "ue_register",         // or "call_ausf_/auth/init" for inter-NF calls
  "nf": "amf",
  "start_time": 1729872345.123,
  "end_time": 1729872345.245,
  "duration_ms": 122.0,
  "status": "ok",                     // "ok" | "error"
  "attributes": {"supi": "imsi-..."}
}
```

### 6.2 Trace context propagation

When NF A calls NF B via NFClient:
1. NFClient gets the current span's `trace_id` and `span_id`
2. Adds headers: `X-Trace-Id: <trace_id>`, `X-Parent-Span-Id: <span_id>`
3. NF B's request handler reads these via `trace_context_from_request(request)`
4. NF B's spans inherit `trace_id` and use NF A's `span_id` as `parent_span_id`

This forms a tree the UI can render as a sequence diagram.

---

## 7. Frontend Architecture

### 7.1 State management

No Redux/Zustand. Component-local `useState` + polling effects. Justified by:
- Most data is server-side anyway
- Polling intervals are 1–5s (cheap)
- Simpler to reason about for a portfolio project

### 7.2 API client (`api.js`)

Single module with one method per backend endpoint:
```javascript
const req = (path, opts) => fetch(path, opts).then(handleResponse)

export const api = {
    topology:      ()        => req('/api/orchestrator/topology'),
    attach:        (count)   => req('/api/orchestrator/subscribers/attach', {method: 'POST', body: ...}),
    injectFailure: (body)    => req('/api/orchestrator/failures/inject', {method: 'POST', body: ...}),
    detectAnomalies: ()      => req('/api/ml/anomalies', {method: 'POST'}),
    diagnose:      ()        => req('/api/llm/diagnose', {method: 'POST'}),
    remediate:     (goal, n) => req('/api/llm/remediate', {method: 'POST', body: ...}),
    // ... etc
}
```

Frontend never calls NFs directly — always through orchestrator/collector/ml/llm.

### 7.3 Nginx reverse proxy

```nginx
location /api/orchestrator/ { rewrite ^/api/orchestrator/(.*) /api/$1 break; proxy_pass http://orchestrator:9001; }
location /api/collector/    { rewrite ^/api/collector/(.*)    /api/$1 break; proxy_pass http://collector:9000; }
location /api/ml/           { proxy_pass http://ml_engine:9002; }
location /api/llm/          { proxy_pass http://llm_agent:9003; proxy_read_timeout 120s; }
location /                  { try_files $uri /index.html; }   # SPA fallback
```

The `proxy_read_timeout 120s` for LLM is important — Claude's tool-use loops can take 60+ seconds.

### 7.4 Sequence diagram renderer (CallFlow.jsx)

The `SequenceDiagram` component walks the spans:
1. Sort by `start_time`
2. For each span:
   - If `parent_span_id` is null and NF is AMF → emit "UE → AMF" arrow at top
   - If `operation` starts with `call_` → emit caller→callee arrow + return arrow
3. Layout: 7 vertical lanes (UE + 6 NFs), arrows stacked vertically by time order
4. Arrow colors: phosphor=request, amber=response, alert=error
5. Latency annotated below each arrow

---

## 8. Scenario Engine Internals

`scenarios.py` defines a `Scenario` dataclass + a `RunContext` helper + 10 scenario functions. Each scenario is an async function that uses the helpers:

```python
async def _scn_auth_storm(ctx: RunContext):
    ctx.log("Phase 1: throttle UDM")
    await ctx.inject("udm", extra_latency_ms=1500, error_rate=0.3)
    await ctx.sleep(2)
    ctx.log("Phase 2: launch 50-UE attach storm")
    await ctx.attach_burst(50, parallelism=20)
    await ctx.sleep(20)
    ctx.log("Phase 4: clear UDM faults")
    await ctx.clear("udm")
```

The `ScenarioRuntime` class manages:
- Cancelling any in-progress scenario before starting a new one
- Always clearing all faults in a `finally` block (even on cancel/exception)
- Recording history (last 50 runs with full logs)

Dynamic loading via `importlib.util.spec_from_file_location` so the orchestrator can keep `scenarios.py` as a sibling file. **Critical**: must register in `sys.modules` before `exec_module` for `@dataclass` to work — see the comment in orchestrator/main.py.

---

## 9. Configuration Reference

### Environment variables

| Variable | Default | Used by |
|----------|---------|---------|
| `SERVICE_NAME` | (required) | All — selects which NF main module to run |
| `PORT` | 8000 | All — uvicorn bind port |
| `NRF_URL` | http://nrf:8001 | All — service discovery target |
| `AUSF_URL` | http://ausf:8002 | AMF, collector, orchestrator |
| `UDM_URL` | http://udm:8003 | AUSF, AMF, collector, orchestrator |
| `AMF_URL` | http://amf:8004 | Orchestrator, collector, llm_agent |
| `SMF_URL` | http://smf:8005 | AMF, collector, orchestrator |
| `UPF_URL` | http://upf:8006 | SMF, collector, orchestrator |
| `PCF_URL` | http://pcf:8007 | SMF, collector, orchestrator |
| `COLLECTOR_URL` | http://collector:9000 | ml_engine, llm_agent |
| `ORCHESTRATOR_URL` | http://orchestrator:9001 | llm_agent |
| `ANTHROPIC_API_KEY` | — | llm_agent (required for LLM tab) |
| `CLAUDE_MODEL` | claude-sonnet-4-5 | llm_agent |

### Tunable constants in code

| File | Constant | Default | Purpose |
|------|----------|---------|---------|
| `collector/main.py` | `SCRAPE_INTERVAL` | 5.0 | Seconds between scrapes |
| `collector/main.py` | `METRIC_HISTORY maxlen` | 720 | 1h of 5s samples |
| `collector/main.py` | `LOGS maxlen` | 2000 | Per-NF |
| `collector/main.py` | `SPANS maxlen` | 2000 | Total |
| `nf_common/__init__.py` | `Telemetry.spans maxlen` | 1000 | Per-NF |
| `nf_common/__init__.py` | `Telemetry.logs maxlen` | 2000 | Per-NF |
| `udm/main.py` | provisioned subs | 1000 | Subscriber pool |
| `ml_engine/main.py` | `IsolationForest n_estimators` | 100 | Tree count |
| `llm_agent/main.py` | `max_iterations` (default) | 8 | Agent loop cap |

---

## 10. Testing Strategy

**Currently implemented**: zero automated tests. This is a deliberate choice for a portfolio project — the test plan would be:

| Layer | Test type | Tool |
|-------|-----------|------|
| Per-NF endpoints | Unit + integration | pytest + httpx.AsyncClient |
| Inter-NF flows | E2E with real Docker stack | pytest-asyncio + docker-compose programmatic API |
| Failure injection | Property-based | hypothesis |
| ML models | Quality + drift | scikit-learn's built-in metrics |
| LLM agent | LLM-as-judge eval | A small evaluation harness running the 10 scenarios and scoring agent diagnoses |
| Frontend | Component | Vitest + Testing Library |
| End-to-end | Browser automation | Playwright |

For now: smoke test by running `docker compose up`, attaching some UEs, injecting a fault, watching the LLM agent diagnose it.

---

## 11. Coding Conventions

- **Python**: PEP 8, 4-space indent, type hints on all function signatures
- **Async everywhere**: All I/O is `async`/`await` (httpx, FastAPI handlers)
- **One responsibility per service**: NFs do their NF thing, orchestrator orchestrates, collector collects
- **Errors propagate as HTTPException**: 4xx for client error, 5xx for server / NF error
- **Logs are JSON**: Structured with consistent fields (`timestamp`, `nf`, `level`, `message`, plus optional `supi`, `trace_id`, etc.)
- **Constants UPPER_CASE**: as Python convention
- **React**: Functional components + hooks only. No classes. Tailwind utility classes only (no CSS modules).

---

## 12. Document Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Initial release | Full LLD covering all 10 services and frontend |
