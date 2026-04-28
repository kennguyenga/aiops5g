# Message Flows — 5G AIOps

Detailed sequence diagrams for every flow in the system. All diagrams are Mermaid (renders on GitHub) with ASCII backups for offline viewing.

**Index:**
- [§1 UE Registration (Attach)](#1-ue-registration-attach)
- [§2 PDU Session Establishment](#2-pdu-session-establishment)
- [§3 UE Deregistration (Detach)](#3-ue-deregistration-detach)
- [§4 Failure Injection](#4-failure-injection)
- [§5 Failure Scenario Execution](#5-failure-scenario-execution)
- [§6 Telemetry Collection](#6-telemetry-collection)
- [§7 ML Anomaly Detection](#7-ml-anomaly-detection)
- [§8 LLM Classifier Diagnosis](#8-llm-classifier-diagnosis)
- [§9 LLM Agent Tool Loop](#9-llm-agent-tool-loop)
- [§10 Call Flow Tracing](#10-call-flow-tracing)
- [§11 NF Service Registration](#11-nf-service-registration)

---

## 1. UE Registration (Attach)

### Trigger
- **UI**: Subscribers tab → "Attach 10 UEs"
- **API**: `POST /api/orchestrator/subscribers/attach`

### Flow

```mermaid
sequenceDiagram
    autonumber
    participant UI as UI / API caller
    participant ORCH as Orchestrator
    participant AMF
    participant AUSF
    participant UDM

    UI->>ORCH: POST /subscribers/attach<br/>{count: 10}
    ORCH->>ORCH: Pick 10 SUPIs from pool<br/>Generate auth keys

    loop For each UE (parallel, up to N concurrent)
        ORCH->>AMF: POST /ue/register<br/>{supi, plmn, ue_auth_key}
        AMF->>AMF: Create UE state (REGISTERING)<br/>Assign amf_ue_id

        Note over AMF,AUSF: Phase 1: AKA Authentication
        AMF->>AUSF: POST /auth/init<br/>{supi}
        AUSF->>UDM: GET /subscribers/{supi}/auth-vector
        UDM->>UDM: Lookup subscriber<br/>Generate (RAND, XRES, AUTN)
        UDM-->>AUSF: 200 OK<br/>{rand, xres, autn}
        AUSF->>AUSF: Store (xres, ausf_session_id)
        AUSF-->>AMF: 200 OK<br/>{rand, autn, ausf_session_id}

        AMF->>AMF: Compute UE_RES = SHA256(K || RAND)[:8]<br/>(simulating UE-side computation)

        AMF->>AUSF: POST /auth/confirm<br/>{supi, session_id, res: UE_RES}
        AUSF->>AUSF: Compare RES vs stored XRES
        AUSF-->>AMF: 200 OK<br/>{authenticated: true}

        Note over AMF,UDM: Phase 2: Subscription fetch
        AMF->>UDM: GET /subscribers/{supi}/profile
        UDM-->>AMF: 200 OK<br/>{nssai, apn_list, plmn}

        AMF->>AMF: state = REGISTERED<br/>Increment registrations_success_total<br/>Emit log + span

        AMF-->>ORCH: 200 OK<br/>{status, supi, amf_ue_id, profile, trace_id}
    end

    ORCH-->>UI: 200 OK<br/>{success: 10, failed: 0, attached: [...]}
```

### Error paths

| Failure point | What happens | Status code | LLM agent symptom |
|---------------|-------------|-------------|-------------------|
| UDM auth-vector fetch fails | AUSF returns 500 → AMF returns 503 | 503 | `auth_init_failures_total` ↑ |
| AUSF compares RES, mismatch | `auth_confirm_failures_total++` | 401 | log: "auth confirmation failed" |
| UDM profile fetch fails | AMF returns 503 | 503 | `registrations_failed_total` ↑ |
| AMF middleware (injected fault) | Returns 500 before any logic | 500 | request never reaches AUSF |

### Telemetry generated per attach

- **Spans**: 7 per successful attach (AMF root, 6 inter-NF calls)
- **Logs**: ~5 (REGISTERING, auth init, auth confirm, profile fetch, REGISTERED)
- **Metrics**: `requests_total++`, `registrations_success_total++`, `active_ues` gauge updated
- **Trace context**: `trace_id` propagated via `X-Trace-Id` header end-to-end

### ASCII version

```
UI         Orchestrator    AMF           AUSF          UDM
 │              │            │              │             │
 │POST /attach │            │              │             │
 │─────────────▶            │              │             │
 │              │POST/register             │             │
 │              │────────────▶              │             │
 │              │            │ POST/auth/init             │
 │              │            │─────────────▶              │
 │              │            │              │GET/auth-vec│
 │              │            │              │────────────▶
 │              │            │              │◀─(rand,xres,autn)
 │              │            │◀─(rand,autn) │             │
 │              │            │POST/auth/confirm           │
 │              │            │─────────────▶              │
 │              │            │◀── ok ───────              │
 │              │            │GET /profile  │             │
 │              │            │───────────────────────────▶│
 │              │            │◀──────────────(nssai,apn) │
 │              │            │ REGISTERED   │             │
 │              │◀───────────│             │             │
 │◀─────────────│            │              │             │
```

---

## 2. PDU Session Establishment

### Trigger
- **UI**: Same as attach (the orchestrator does attach + session in one call)
- **Direct API**: `POST /ue/session` on AMF

### Flow

```mermaid
sequenceDiagram
    autonumber
    participant AMF
    participant SMF
    participant PCF
    participant UPF

    Note over AMF: UE already REGISTERED
    AMF->>SMF: POST /sessions<br/>{supi, apn: "internet"}
    SMF->>SMF: Create PDUSession(state=PENDING, pdu_id)

    Note over SMF,PCF: Step 1 — Policy decision
    SMF->>PCF: POST /policies/decide<br/>{supi, apn}
    PCF->>PCF: Lookup template by APN<br/>(qos_5qi, max_mbps, etc.)
    PCF->>PCF: Store active policy
    PCF-->>SMF: 200 OK<br/>{qos_5qi, max_dl_mbps, ...}

    Note over SMF,UPF: Step 2 — Bearer install
    SMF->>UPF: POST /bearers<br/>{pdu_id, supi, qos_5qi}
    UPF->>UPF: Allocate bearer_id<br/>Add to BEARERS dict<br/>(KPI engine picks it up next tick)
    UPF-->>SMF: 200 OK<br/>{bearer_id, ...}

    SMF->>SMF: session.state = ACTIVE<br/>Update active_sessions gauge
    SMF-->>AMF: 200 OK<br/>{pdu_id, state: ACTIVE, bearer_id, ...}
    AMF-->>AMF: ue.pdu_sessions.append(pdu_id)
```

### Error handling — what makes this realistic

If **PCF** fails:
1. SMF logs `pcf_error`, increments `sessions_failed_total{reason="pcf_error"}`
2. Session state stays `PENDING` (later marked FAILED)
3. SMF returns 503 to AMF
4. **No UPF call is made** — bearer wasn't installed

If **UPF** fails after PCF succeeded:
1. SMF logs `upf_error`
2. Best-effort cleanup: SMF calls `DELETE /policies/{supi}` on PCF to roll back
3. Session state = FAILED
4. SMF returns 503

This rollback pattern is exactly what real telco SMFs do. The LLM agent can detect both signatures: "policy issued but no bearer" vs "no policy at all" indicates *which* downstream NF failed.

### KPI propagation

Once a bearer is installed, UPF's KPI engine (1Hz background loop) starts including it in:
- `total_dl_mbps` += per-bearer rate (depends on 5QI)
- `active_bearers` gauge += 1
- `bearers_5qi_<N>` gauge += 1

Visible in Topology tab's "UPF Data Plane KPIs" panel within 1 second.

---

## 3. UE Deregistration (Detach)

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant ORCH as Orchestrator
    participant AMF
    participant SMF
    participant UPF
    participant PCF

    UI->>ORCH: POST /subscribers/detach<br/>{count: N}
    ORCH->>ORCH: Pick N attached SUPIs

    loop For each UE
        ORCH->>AMF: POST /ue/deregister<br/>{supi}
        AMF->>AMF: state = DEREGISTERING

        loop For each pdu_session
            AMF->>SMF: DELETE /sessions/{pdu_id}
            SMF->>UPF: DELETE /bearers/{bearer_id}<br/>(best-effort)
            UPF-->>SMF: 200 OK
            SMF->>PCF: DELETE /policies/{supi}<br/>(best-effort)
            PCF-->>SMF: 200 OK
            SMF->>SMF: session.state = RELEASED
            SMF-->>AMF: 200 OK
        end

        AMF->>AMF: state = DEREGISTERED<br/>Decrement active_ues gauge
        AMF-->>ORCH: 200 OK<br/>{status: deregistered, trace_id}
    end

    ORCH-->>UI: 200 OK<br/>{detached: [...]}
```

**Cleanup philosophy**: best-effort. If UPF/PCF fail during cleanup, AMF still marks the UE as DEREGISTERED. Better to have orphan bearers/policies than zombie UEs blocking re-attach.

---

## 4. Failure Injection

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant ORCH as Orchestrator
    participant TARGET as Target NF (e.g. AMF)

    UI->>ORCH: POST /failures/inject<br/>{nf: "amf", error_rate: 0.5, extra_latency_ms: 1000}
    ORCH->>ORCH: Validate request<br/>Look up target NF URL
    ORCH->>TARGET: POST /failure<br/>{error_rate: 0.5, extra_latency_ms: 1000}
    TARGET->>TARGET: Update failure_config<br/>(in-memory)
    TARGET-->>ORCH: 200 OK<br/>{updated_config}
    ORCH-->>UI: 200 OK

    Note over TARGET: All subsequent requests now run through<br/>middleware that applies the config

    rect rgb(40, 30, 30)
        Note over TARGET: Effect on next request
        participant CALLER as Some other NF
        CALLER->>TARGET: GET /healthz (or any endpoint)
        TARGET->>TARGET: Middleware:<br/>1. sleep extra_latency_ms<br/>2. coin-flip on error_rate<br/>3. coin-flip on corruption_rate
        alt error_rate triggered
            TARGET-->>CALLER: 500 Internal Server Error
        else corruption_rate triggered
            TARGET-->>CALLER: 200 OK<br/>{...mangled body...}
        else normal
            TARGET-->>CALLER: 200 OK
        end
    end
```

### Fault config schema

```json
{
  "error_rate": 0.0,         // 0.0–1.0, returns HTTP 500 with this probability
  "extra_latency_ms": 0,     // added to every request (sync sleep)
  "blackhole": false,        // hangs request 30s then 503 (simulates timeout)
  "corruption_rate": 0.0,    // returns mangled response body
  "unhealthy": false         // /healthz returns 503 but service responds otherwise
}
```

---

## 5. Failure Scenario Execution

Scenarios are scripted multi-step sequences. Example: `auth-storm`.

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant ORCH as Orchestrator
    participant SCN as scenarios.py runner
    participant UDM
    participant AMF as AMF (during attach)

    UI->>ORCH: POST /scenarios/auth-storm/run
    ORCH->>SCN: spawn asyncio task<br/>scn.run_scenario("auth-storm")
    ORCH-->>UI: 200 OK<br/>{started: "auth-storm"}

    Note over SCN: Phase 1
    SCN->>SCN: log("INJECT udm ←<br/>extra_latency_ms=1500, error_rate=0.3")
    SCN->>UDM: POST /failure<br/>{extra_latency_ms: 1500, error_rate: 0.3}
    UDM-->>SCN: 200 OK
    SCN->>SCN: sleep(2)

    Note over SCN: Phase 2
    SCN->>SCN: log("ATTACH burst: 50 UEs")
    par Parallel attach burst (sem=20)
        SCN->>AMF: POST /ue/register × 50
        Note over AMF,UDM: Many fail due to UDM throttle
    end
    SCN->>SCN: log("ATTACH burst: 23/50 succeeded")

    Note over SCN: Phase 3
    SCN->>SCN: sleep(20)<br/>(let metrics accumulate)

    Note over SCN: Phase 4
    SCN->>SCN: log("CLEAR udm")
    SCN->>UDM: POST /failure<br/>{cleared}
    UDM-->>SCN: 200 OK

    Note over SCN: finally block
    SCN->>SCN: clear_all() — extra safety<br/>history.append(this run)

    loop UI polls every 2s
        UI->>ORCH: GET /scenarios/state
        ORCH-->>UI: {running: bool, scenario_id, logs: [...]}
    end
```

**Cancellation**: If UI clicks "Stop" or another scenario is started, the `asyncio.Task` is cancelled. The `finally` block always clears all faults — guaranteed clean state after every scenario.

---

## 6. Telemetry Collection

```mermaid
sequenceDiagram
    autonumber
    participant COLL as Collector
    participant NRF
    participant AMF
    participant SMF
    participant Other as ...other NFs

    Note over COLL: Background task: every 5s

    loop Every SCRAPE_INTERVAL (5s)
        par Scrape all NFs in parallel
            COLL->>NRF: GET /metrics
            COLL->>AMF: GET /metrics
            COLL->>SMF: GET /metrics
            COLL->>Other: GET /metrics
        end

        par
            COLL->>NRF: GET /logs?since={last_scrape}
            COLL->>AMF: GET /logs?since={last_scrape}
            COLL->>SMF: GET /logs?since={last_scrape}
            COLL->>Other: GET /logs?since={last_scrape}
        end

        par
            COLL->>NRF: GET /traces
            COLL->>AMF: GET /traces
            COLL->>SMF: GET /traces
            COLL->>Other: GET /traces
        end

        Note over COLL: For each NF response:<br/>METRIC_HISTORY[nf].append((t, snapshot))<br/>LOGS[nf].extend(new_logs)<br/>SPANS.extend(new_spans)<br/>LAST_SEEN[nf] = time.time()

        Note over COLL: If a request fails (timeout / connection error):<br/>just skip — LAST_SEEN not updated<br/>UI will show that NF as unreachable
    end
```

**Why poll instead of push?** Polling is simpler, the NFs don't need to know about the collector, and 5s is fine granularity for a simulator. Production systems would push via OpenTelemetry OTLP exporter.

---

## 7. ML Anomaly Detection

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant ML as ML Engine
    participant COLL as Collector

    UI->>ML: POST /api/ml/anomalies (no body = scan all NFs)
    ML->>ML: For each NF in [nrf, ausf, udm, amf, smf, upf, pcf]:
    loop per NF
        ML->>COLL: GET /api/metrics/{nf}
        COLL-->>ML: 300s of metric snapshots

        ML->>ML: Build feature matrix:<br/>[(req_rate, err_rate, p99_lat) per 30s window]

        alt samples >= 10
            ML->>ML: model = IsolationForest(n_est=100)<br/>scores = model.fit_predict(X)
            ML->>ML: anomalies = where(scores == -1)
        else not enough data
            ML->>ML: result["note"] = "insufficient samples"
        end
    end

    ML-->>UI: 200 OK<br/>{results: [{nf, samples, anomaly_count, anomalies: [{timestamp, score, ...}]}, ...]}
```

**Why Isolation Forest?**
- No labels needed (unsupervised)
- Handles multivariate data (3 features per sample)
- Fast — fits 100 trees on ~50 samples in <100ms
- Anomalies are "easy to isolate" — high scoring points get fewer splits

**When it works well**: sudden, large deviations from baseline (e.g. error rate jumps from 0.1% to 30%).

**When it doesn't**: gradual drift (use Ridge forecast for that), or anomalies that look like normal spikes (use rate-of-change features instead).

---

## 8. LLM Classifier Diagnosis

Single-shot Claude call. No tools. Returns structured JSON.

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant LLM as LLM Agent
    participant COLL as Collector
    participant ORCH as Orchestrator
    participant CLAUDE as Anthropic API

    UI->>LLM: POST /api/llm/diagnose
    LLM->>COLL: GET /api/summary (high-level state)
    COLL-->>LLM: {nfs: {amf: {requests, errors, p99_lat}, ...}}
    LLM->>COLL: GET /api/logs?level=error&limit=50
    COLL-->>LLM: Recent error logs across NFs
    LLM->>ORCH: GET /api/failures/state
    ORCH-->>LLM: {amf: {error_rate: 0.5, ...}, ...}

    LLM->>LLM: Build prompt:<br/>SYSTEM_PROMPT + telemetry summary

    LLM->>CLAUDE: POST /v1/messages<br/>{model, system, messages: [user telemetry]}
    Note over CLAUDE: Claude analyzes,<br/>returns structured JSON
    CLAUDE-->>LLM: 200 OK<br/>{content: [{type: text, text: "{...JSON...}"}]}

    LLM->>LLM: Parse JSON from text<br/>(or fallback to raw)

    LLM-->>UI: 200 OK<br/>{diagnosis: {root_cause, affected_nf, severity, evidence, recommended_actions, confidence}}
```

### Prompt skeleton

```
System: You are a 5G network SRE. You analyze telemetry from a microservice
5G core (NRF, AUSF, UDM, AMF, SMF, UPF, PCF) and identify root causes.

The 5G registration flow is: UE → AMF → AUSF → UDM ...
Common failure modes: ...

Respond ONLY with JSON matching this schema:
{
  "root_cause": str,
  "affected_nf": str,
  "severity": "low" | "medium" | "high" | "critical",
  "evidence": [str],
  "recommended_actions": [str],
  "confidence": float (0-1)
}

User: Here is the current 5G core telemetry:
TOPOLOGY: { ... }
METRICS SUMMARY: { ... }
RECENT ERROR LOGS (last 50): [ ... ]
INJECTED FAILURES: { ... }

Diagnose any active issues.
```

---

## 9. LLM Agent Tool Loop

The autonomous mode. Claude decides what to investigate, calls tools, observes results, decides what to do next. Loops until it stops calling tools.

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant LLM as LLM Agent
    participant CLAUDE as Anthropic API
    participant COLL as Collector
    participant ORCH as Orchestrator

    UI->>LLM: POST /api/llm/remediate<br/>{goal: "Investigate and fix any issues"}
    LLM->>LLM: messages = [{role: user, content: goal}]<br/>iteration = 0

    loop until stop_reason != "tool_use" or iteration >= 8
        LLM->>CLAUDE: POST /v1/messages<br/>{model, system, messages, tools: TOOLS}

        alt Claude wants to investigate
            CLAUDE-->>LLM: stop_reason: "tool_use"<br/>content: [<br/>  {type: text, "Let me check the AMF logs"},<br/>  {type: tool_use, name: "read_logs", input: {nf: "amf", level: "error"}}<br/>]

            LLM->>LLM: For each tool_use block:
            alt tool == "read_logs"
                LLM->>COLL: GET /api/logs?nf=amf&level=error
                COLL-->>LLM: {logs: [...]}
            else tool == "query_metrics"
                LLM->>COLL: GET /api/metrics/{nf}
                COLL-->>LLM: {metrics: {...}}
            else tool == "list_failures"
                LLM->>ORCH: GET /api/failures/state
                ORCH-->>LLM: {amf: {error_rate: 0.5, ...}}
            else tool == "clear_failure"
                LLM->>ORCH: POST /api/failures/clear?nf=amf
                ORCH-->>LLM: {cleared: "amf"}
            end

            LLM->>LLM: Append messages:<br/>[assistant: tool_use response, user: tool_results]
            LLM->>LLM: iteration++

        else Claude is done
            CLAUDE-->>LLM: stop_reason: "end_turn"<br/>content: [{type: text, "Issue resolved. ..."}]
            LLM->>LLM: break loop
        end
    end

    LLM-->>UI: 200 OK<br/>{transcript: [each step with content + tool_results], iterations}
```

### Real example transcript (annotated)

```
ITERATION 1 (stop_reason: tool_use)
  text: "I'll start by checking the topology and any active failures."
  tool_use: get_topology
  tool_use: list_failures

  → tool_results: {topology: ..., failures: {amf: {error_rate: 0.5}}}

ITERATION 2 (stop_reason: tool_use)
  text: "I see a 50% error rate injected on AMF. Let me check its logs."
  tool_use: read_logs(nf="amf", level="error")

  → tool_results: {logs: ["registrations_failed_total++", ...]}

ITERATION 3 (stop_reason: tool_use)
  text: "Confirmed: AMF is the issue. Clearing the fault."
  tool_use: clear_failure(nf="amf")

  → tool_results: {cleared: "amf"}

ITERATION 4 (stop_reason: tool_use)
  text: "Verifying recovery..."
  tool_use: list_failures

  → tool_results: {} (empty)

ITERATION 5 (stop_reason: end_turn)
  text: "## Summary
         - Root cause: 50% error_rate fault injected on AMF
         - Action: cleared the fault via clear_failure(amf)
         - Verification: list_failures confirms no active faults
         - System is healthy."
```

---

## 10. Call Flow Tracing

The Call Flow visualizer triggers a flow with a known trace_id, then reconstructs the sequence diagram from spans.

```mermaid
sequenceDiagram
    autonumber
    participant UI as UI (CallFlow tab)
    participant ORCH as Orchestrator
    participant AMF
    participant AUSF
    participant UDM
    participant COLL as Collector

    UI->>ORCH: POST /api/callflow/trace<br/>{flow: "attach_and_session", supi: "imsi-..."}
    ORCH->>ORCH: trace_id = uuid.uuid4().hex
    ORCH->>AMF: POST /ue/register<br/>headers: X-Trace-Id: {trace_id}
    AMF->>AMF: span(trace_id=..., op="ue_register")
    AMF->>AUSF: POST /auth/init<br/>headers: X-Trace-Id, X-Parent-Span-Id
    Note over AUSF: span inherits trace_id<br/>parent = AMF's span
    AUSF->>UDM: GET /auth-vector
    Note over UDM: span inherits trace_id<br/>parent = AUSF's span
    UDM-->>AUSF: 200
    AUSF-->>AMF: 200
    AMF->>UDM: GET /profile
    UDM-->>AMF: 200
    AMF-->>ORCH: 200<br/>{trace_id, ...}
    ORCH->>ORCH: sleep(1.0)<br/>(let collector scrape)
    ORCH-->>UI: 200<br/>{trace_id, supi, attach_status, ...}

    loop Poll for spans (up to 8 times, 1.5s apart)
        UI->>COLL: GET /api/traces?trace_id={trace_id}
        COLL-->>UI: {spans: [...]}
    end

    UI->>UI: Render SVG sequence diagram:<br/>1. Sort spans by start_time<br/>2. Identify root span (parent_span_id null)<br/>3. Walk spans, emit arrows<br/>4. Color: green=request, amber=response, red=error
```

### Span tree for a successful attach + session

```
ue_register (AMF)                        [trace_id=X, span=A, parent=null]
├── call_ausf_/auth/init (AMF)          [trace_id=X, span=B, parent=A]
│   └── auth_init (AUSF)                [trace_id=X, span=C, parent=B]
│       └── call_udm_/auth-vector (AUSF)[trace_id=X, span=D, parent=C]
│           └── get_auth_vector (UDM)   [trace_id=X, span=E, parent=D]
├── call_ausf_/auth/confirm (AMF)       [trace_id=X, span=F, parent=A]
│   └── auth_confirm (AUSF)             [trace_id=X, span=G, parent=F]
└── call_udm_/profile (AMF)             [trace_id=X, span=H, parent=A]
    └── get_profile (UDM)               [trace_id=X, span=I, parent=H]
```

The CallFlow.jsx renderer turns this into the sequence diagram by walking child spans of root in start_time order and emitting arrows for each `call_<nf>_*` span.

---

## 11. NF Service Registration

Happens once at NF startup. Demonstrated with AMF, applies to all NFs.

```mermaid
sequenceDiagram
    autonumber
    participant AMF as AMF (starting up)
    participant NRF

    Note over AMF: Container starts
    Note over AMF: uvicorn binds to 0.0.0.0:8004
    Note over AMF: nf_common.create_nf_app() called

    AMF->>AMF: Build ServiceInstance:<br/>{nf_type: "amf",<br/> nf_instance_id: uuid,<br/> ip_endpoint: "http://amf:8004"}

    loop Until success or 5 retries
        AMF->>NRF: POST /services/register<br/>{nf_type, nf_instance_id, ip_endpoint}
        alt NRF reachable
            NRF->>NRF: services_registered["amf"].append(...)
            NRF-->>AMF: 200 OK<br/>{registered: true}
        else NRF not yet up
            NRF--xAMF: ConnectionRefused
            AMF->>AMF: log warn, sleep 2s, retry
        end
    end

    Note over AMF: Service is now discoverable<br/>via GET /services/amf
```

**docker-compose `depends_on`** ensures NRF starts first and is healthy (via its `/healthz` healthcheck) before any other NF tries to register. So in practice retries rarely happen, but the code handles transient NRF outages anyway.

---

## Appendix: How to read these diagrams

- **Solid arrow** (`-->`): synchronous request
- **Dashed arrow** (`-->>`): response
- **`Note over X,Y`**: behavior or state change
- **`alt/else`**: conditional branches
- **`par`**: parallel execution
- **`loop`**: iteration
- **`rect`**: visual grouping for emphasis
- **autonumber**: each step gets a sequential number for easy reference

For the ASCII versions, vertical lines are NF lifelines (time flows downward), horizontal arrows are messages.
