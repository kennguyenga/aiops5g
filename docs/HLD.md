# High-Level Design (HLD) — 5G AIOps

**Document Status:** Draft v1.0
**Audience:** Architects, technical reviewers, stakeholders
**Scope:** End-to-end design of a simulated 5G core network with ML-based anomaly detection and an LLM-powered SRE agent

---

## 1. Purpose & Goals

### 1.1 Problem Statement

Real 5G core networks are operationally complex: 7+ network functions, dozens of inter-NF API calls per UE, three telemetry pillars (logs/metrics/traces), and failure modes that span service-level (a crashed NF), network-level (latency, packet loss), and security-level (auth failures). When something breaks at 3am, an SRE must:

1. Identify *which* NF is the root cause among many symptoms
2. Distinguish a real incident from transient noise
3. Apply a remediation that doesn't make things worse

This is a perfect domain for AIOps — but most public 5G simulators (Open5GS, free5GC) target protocol compliance, not operations. There's no good testbed for trying out AI/ML approaches against realistic telco failure patterns.

### 1.2 Solution

A **simulated 5G core** with all the operational complexity (microservices, telemetry, faults, scenarios) but **none of the telco-specific overhead** (no real RAN, no GTP-U, no NAS messaging). Layered on top:

- An **ML engine** that does Isolation Forest anomaly detection and Ridge regression forecasting per NF
- An **LLM SRE agent** powered by Claude that can autonomously diagnose and remediate failures using tools
- A **rich UI** for both demos and manual exploration

### 1.3 Non-Goals

- Not a real 5G core — crypto is toy, no real protocol stacks
- Not a benchmark — designed for AIOps experimentation, not throughput tests
- Not multi-tenant — single-operator simulation
- Not production-ready security — no TLS, no auth on the API

---

## 2. System Context

```
                 ┌───────────────────────────────────┐
                 │      Engineer / Operator          │
                 │   (browser at localhost:5173)     │
                 └───────────────┬───────────────────┘
                                 │
                                 │ HTTP / JSON
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │                                                  │
        │            5G AIOps PLATFORM                     │
        │                                                  │
        │   ┌─────────────┐   ┌──────────────────────┐    │
        │   │   UI (8 tabs)│   │  Backend (10 services)│    │
        │   └─────────────┘   └──────────────────────┘    │
        │                                                  │
        └──────────────────────────────────────────────────┘
                                 │
                                 │ HTTPS (only for LLM)
                                 ▼
                 ┌───────────────────────────────────┐
                 │       Anthropic Claude API        │
                 │      (claude-sonnet-4-5)          │
                 └───────────────────────────────────┘
```

**External dependencies:** only the Anthropic API (and only when the LLM Agent tab is used). Everything else is self-contained Docker containers.

---

## 3. Architectural Principles

The design follows a few clear principles:

| Principle | Implementation |
|-----------|----------------|
| **Microservices over monolith** | Each NF is its own FastAPI service in its own container. Failures are isolated. |
| **Service-Based Interface (SBI)** | All inter-NF traffic is HTTP/JSON, mirroring 3GPP Rel-15+ design. |
| **Three-pillar observability** | Every NF emits structured logs (JSON), Prometheus-style metrics, and W3C-style trace spans. |
| **Fault injection as first-class** | Every NF has a `/failure` endpoint. The orchestrator can poke it. ML and LLM agent see the consequences. |
| **AIOps as native, not bolted on** | The ML engine and LLM agent are core services with their own ports and APIs, not afterthoughts. |
| **Single Docker image, multiple roles** | All Python services share one Dockerfile. The `SERVICE_NAME` env var picks the role. Reduces build time and image count. |
| **Deterministic for testing** | Subscriber auth keys are derived from SUPI (`f"{i:032x}"`), so the same SUPI always works. |

---

## 4. Component Inventory

### 4.1 5G Core Network Functions (7)

| NF | Container Port | Role | Key State |
|----|---------------|------|-----------|
| **NRF** | 8001 | Network Repository Function — service registry | `services_registered: dict[nf_type, list[ServiceInstance]]` |
| **AUSF** | 8002 | Authentication Server — runs AKA challenge/response | `auth_sessions: dict[supi, AuthSession]` (in-flight only) |
| **UDM** | 8003 | Unified Data Management — subscriber DB | `subscribers: dict[supi, Subscriber]` (1000 pre-provisioned) |
| **AMF** | 8004 | Access & Mobility — UE registration entry point | `ues: dict[supi, UE]` (registered UEs) |
| **SMF** | 8005 | Session Management — PDU session orchestration | `sessions: dict[pdu_id, PDUSession]` |
| **UPF** | 8006 | User Plane — bearer install + KPI generation | `bearers: dict[bearer_id, Bearer]` + KPI engine |
| **PCF** | 8007 | Policy Control — QoS/charging decisions | `active_policies: dict[supi, Policy]` |

### 4.2 Control & AI Plane (4)

| Service | Container Port | Role |
|---------|---------------|------|
| **Collector** | 9000 | Scrapes `/metrics`, `/logs`, `/traces` from every NF every 5s. In-memory ring buffers. |
| **Orchestrator** | 9001 | UE simulator + failure injection + scenario runner. Bridges UI to NFs. |
| **ML Engine** | 9002 | Isolation Forest (anomaly detection) + Ridge regression (forecasting) on collector data |
| **LLM Agent** | 9003 | Claude classifier (single-shot) + autonomous tool-using agent loop |

### 4.3 Frontend (1)

| Component | Container Port | Role |
|-----------|---------------|------|
| **Frontend** | 80 (host 5173) | nginx serving the React SPA + reverse proxy to all backend services |

---

## 5. High-Level Data Flow

### 5.1 The AIOps loop (the central use case)

```
     ┌─────────────────────────────────────────────────────────────┐
     │                                                             │
     │   1. NORMAL OPERATION                                       │
     │      UEs attach → AKA exchange → PDU sessions → KPIs flow   │
     │                                                             │
     │   2. FAULT INJECTION                                        │
     │      Operator (or scenario script) injects a failure        │
     │                                                             │
     │   3. SYMPTOMS APPEAR                                        │
     │      • Metrics: error rate spikes, latency climbs           │
     │      • Logs: warning/error entries multiply                 │
     │      • Traces: spans return error status                    │
     │                                                             │
     │   4. DETECTION                                              │
     │      ML engine flags anomalies on next scan                 │
     │      OR operator notices in UI                              │
     │                                                             │
     │   5. DIAGNOSIS                                              │
     │      LLM agent reads telemetry, identifies root cause       │
     │                                                             │
     │   6. REMEDIATION                                            │
     │      LLM agent calls clear_failure tool                     │
     │      OR operator clicks "Clear" in UI                       │
     │                                                             │
     │   7. VERIFICATION                                           │
     │      Telemetry confirms recovery                            │
     │      Loop back to NORMAL OPERATION                          │
     │                                                             │
     └─────────────────────────────────────────────────────────────┘
```

### 5.2 Key data paths

1. **Subscriber lifecycle** — UI → orchestrator → AMF → (AUSF, UDM, SMF, PCF, UPF) → response
2. **Telemetry collection** — collector polls every NF every 5s via 3 endpoints
3. **Failure injection** — UI → orchestrator → NF `/failure` endpoint → middleware applies fault
4. **AI inference** — ML/LLM read from collector (and orchestrator for state) → return verdict to UI

---

## 6. Quality Attributes

### 6.1 Performance

| Metric | Target | Actual |
|--------|--------|--------|
| Time to attach 1 UE | <500ms | ~50–200ms typical |
| Concurrent UE attaches | 50+ | Tested with `flash-crowd` scenario (200 UEs in 10s) |
| Telemetry scrape interval | 5s | Configurable in `collector/main.py` |
| LLM diagnosis latency | <30s | Typically 5–15s depending on Claude model |
| LLM agent loop (full remediation) | <90s | Capped at 8 iterations |

### 6.2 Scalability

The system is intentionally single-instance per NF (no horizontal scaling). To add scale-out:
- NRF would need a real backend (etcd, Consul) instead of in-memory dict
- Collector would need to handle multiple replicas of each NF
- All in-memory state would need to move to Redis or Postgres

This is left as future work — not needed for an AIOps testbed.

### 6.3 Reliability

- **Failure isolation**: Each NF in its own container. AMF crashing doesn't take down SMF.
- **Health checks**: Every NF exposes `/healthz`. Collector and orchestrator track per-NF reachability.
- **Graceful degradation**: When the LLM Agent's API key is missing, the rest of the system works fine.

### 6.4 Observability

The system exemplifies the observability it teaches: every internal call is traced, every state change is logged, every counter is surfaced in metrics. The collector aggregates everything for both human operators (UI) and AI consumers (ML/LLM).

### 6.5 Security

**Out of scope for this version.** No TLS, no auth on the API, no input validation beyond Pydantic. The toy AKA crypto uses SHA-256 — never use this for anything real.

---

## 7. Technology Choices & Rationale

| Choice | Why |
|--------|-----|
| **Python 3.11 + FastAPI** | Best-in-class for HTTP microservices with async support. Pydantic gives free validation. OpenAPI auto-generated. |
| **React + Vite + Tailwind** | Fast dev loop, no Webpack pain, utility CSS that doesn't bloat. |
| **Docker Compose** | Simplest possible multi-container orchestration. K8s would be overkill. |
| **In-memory state** | Forces simplicity. Restarts wipe state, but for a simulator that's fine — see UDM provisioning 1000 subscribers on startup. |
| **scikit-learn for ML** | Industry standard, no GPU needed, fast enough for streaming data. |
| **Claude Sonnet 4.5** | Strong reasoning + tool use. Other LLMs would work but tool-use quality varies. |
| **W3C-style trace propagation** | Industry standard. Trace context survives across HTTP calls via headers. |
| **JSON structured logs** | Both human-greppable and machine-parseable. The LLM agent reads them directly. |

---

## 8. Constraints & Assumptions

### Constraints
- All services must run on a single host (no distributed deployment in this version)
- No persistent storage — all state in memory
- Single Anthropic API key (no key rotation)
- No multi-tenancy

### Assumptions
- Operator trusts the LLM agent to call remediation tools (`clear_failure`)
- Anthropic API is reachable
- Docker Desktop's bridge network works (no host-network mode issues)
- The 1000 pre-provisioned subscribers are enough for any demo

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Docker port conflicts on Windows | High (we hit this!) | Stack won't start | Renumbered all host ports to 18xxx range |
| LLM agent infinite loops | Low | Wasted API tokens | Hard cap at 8 iterations |
| LLM hallucinates a remediation | Medium | False fix | Tool calls return real results; agent sees if recovery actually happens |
| Telemetry buffers fill up under heavy load | Low | Old data dropped | Acceptable — ring buffers by design |
| Concurrent fault injection conflicts | Low | Conflicting state | Last-write-wins on `/failure` endpoint |
| Anthropic API down | Low | LLM tab unavailable | Other tabs unaffected |

---

## 10. Future Work

Things that would make this production-grade (none done):

- Real OpenTelemetry SDK + Prometheus + Grafana + Tempo backend
- Persistent state (Redis for sessions, Postgres for subscribers, S3 for trace history)
- Multi-replica NFs behind load balancers
- AuthN/Z on all APIs (mTLS + OAuth2)
- Real cryptography (use a library like cryptography or pycryptodome)
- A real RAN simulator (UERANSIM integration)
- Kubernetes manifests for deployment
- More ML models (LSTM for time-series, GNN for topology-aware anomaly detection)
- Multi-LLM support (route to GPT-4, Gemini, etc. based on task)
- A formal evaluation harness (predict scenario outcome from telemetry, measure agent accuracy)

---

## Appendix A: Glossary

| Term | Meaning |
|------|---------|
| **AKA** | Authentication and Key Agreement — the 5G mutual auth protocol |
| **AMF** | Access and Mobility Management Function |
| **APN** | Access Point Name (e.g. "internet", "ims") |
| **AUSF** | Authentication Server Function |
| **Bearer** | A logical data path between UE and PDN through UPF |
| **NF** | Network Function — generic term for 5G control/user plane services |
| **NRF** | Network Repository Function — service registry |
| **PCF** | Policy Control Function |
| **PDU Session** | Packet Data Unit session — the UE's data connection |
| **5QI** | 5G QoS Identifier (1=voice, 5=video, 9=internet) |
| **SBI** | Service-Based Interface — REST/HTTP between NFs |
| **SMF** | Session Management Function |
| **SUPI** | Subscription Permanent Identifier — what the IMSI evolved into |
| **UDM** | Unified Data Management — subscriber DB |
| **UE** | User Equipment — the phone/device |
| **UPF** | User Plane Function — moves user packets |

---

## Appendix B: Document Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Initial release | First HLD covering 7 NFs, ML, LLM, scenarios, call flow viz |
