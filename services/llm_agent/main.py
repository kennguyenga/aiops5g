"""
LLM Agent — Claude-powered SRE for the 5G core.

Two modes:
  1. CLASSIFIER (/api/llm/diagnose) — single-shot. Reads recent telemetry,
     identifies root cause, suggests remediation. No actions taken.
  2. AGENT (/api/llm/remediate) — tool-using loop. Investigates with tools,
     forms hypotheses, executes remediation, verifies the fix.

Tools available to the agent:
  - read_logs(nf, level, supi, since) — query logs from collector
  - query_metrics(nf, window) — get NF metric snapshot
  - get_topology() — current health of all NFs
  - list_failures() — what failures are currently injected
  - clear_failure(nf) — remediation: clear injected failure
  - inject_failure(nf, type, intensity) — for chaos testing only
"""
import json
import os
import sys
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://collector:9000")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:9001")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

app = FastAPI(title="5G AIOps LLM Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/healthz")
def health():
    return {"status": "ok", "claude_configured": bool(ANTHROPIC_API_KEY)}


# ============================================================================
# CLASSIFIER MODE — single-shot diagnosis
# ============================================================================
SYSTEM_PROMPT_CLASSIFIER = """You are a senior SRE for a 5G mobile core network. \
You analyze telemetry from a microservice 5G core (NRF, AUSF, UDM, AMF, SMF, UPF, PCF) and identify root causes of issues.

The 5G registration flow is:
  UE → AMF → AUSF → UDM (auth vector) → AUSF → UDM (profile) → REGISTERED
PDU session establishment (after registration):
  UE → AMF → SMF → PCF (policy decision) → UPF (install bearer) → ACTIVE
KPI plane (UPF only):
  UPF emits throughput, packet_loss_pct, jitter_ms, active_bearers as gauges every 1s.

Common failure modes:
  • NF crash / blackhole — NF unreachable, all calls timeout
  • NF slowdown — extra latency injected, p99 spikes
  • NF error_rate — NF returns 500s probabilistically
  • Auth failure — AKA mismatch (wrong key) or unknown SUPI in UDM
  • UE state stuck — UE in REGISTERING/AUTHENTICATING and not progressing
  • SUBSCRIBER-LEVEL FAILURES — individual subscribers can be in non-ACTIVE
    states (BLOCKED, ROAMING_NOT_ALLOWED, AUTH_KEY_REVOKED, SUSPENDED,
    PROVISIONING_PENDING). When AMF/AUSF query a non-ACTIVE subscriber,
    UDM returns the corresponding 5G error code. This produces a
    distinctive symptom: errors clustered around specific SUPIs even when
    no NF-level fault is injected.

5G ERROR CODES YOU'LL SEE (use query_error_codes to list current counts):
  AUTH category (auth-flow failures):
    • AUTH_REJECTED       — RES verification failed at AUSF
    • UE_AUTH_KEY_REVOKED — subscriber's K is revoked → blocks auth-vector
    • MAC_FAILURE         — message authentication code mismatch
    • SYNCH_FAILURE       — SQN out of sync (re-sync needed)
  SUBSCRIPTION category (UDM-side, per-subscriber):
    • USER_NOT_FOUND      — SUPI not provisioned
    • USER_NOT_ALLOWED    — subscription does not permit 5GS
    • ILLEGAL_UE          — administratively blocked
    • ROAMING_NOT_ALLOWED — roaming restriction for this PLMN/TAI
    • PLMN_NOT_ALLOWED    — UE's serving PLMN not in allowed list
  SESSION category (SMF/PCF):
    • DNN_NOT_SUPPORTED   — APN not configured
    • PDU_TYPE_NOT_ALLOWED — IPv4/IPv6 restriction
    • CONTEXT_NOT_FOUND   — stale UE/session reference
    • INSUFFICIENT_SLICE_RESOURCES — slice capacity exhausted
  RESOURCE category (any NF):
    • INSUFFICIENT_RESOURCES — UPF can't install bearer / SMF can't allocate
    • NF_CONGESTION       — NF in overload, rejecting new work
    • TOO_MANY_REQUESTS   — rate-limited

DIAGNOSIS HEURISTICS:
  • Many AUTH_REJECTED with no AUSF fault → check subscriber states (UDM)
  • DNN_NOT_SUPPORTED on PCF only → APN config issue, not subscriber
  • CONTEXT_NOT_FOUND across multiple NFs → recent NF restart
  • INSUFFICIENT_RESOURCES on UPF cascades to SMF as upf_error
  • Mixed UDM codes (ILLEGAL_UE + ROAMING_NOT_ALLOWED + AUTH_KEY_REVOKED)
    → bulk subscriber state issue; consider reset_subscribers tool

Given the telemetry below, output JSON:
{
  "root_cause": "<one-sentence summary>",
  "affected_nf": "<nf name or 'multiple'>",
  "severity": "low|medium|high|critical",
  "evidence": ["<bullet>", ...],
  "recommended_actions": ["<action>", ...],
  "confidence": 0.0-1.0
}

Be specific. Cite metric names and counts. If telemetry is sparse, say so."""


class DiagnoseRequest(BaseModel):
    extra_context: Optional[str] = None


@app.post("/api/llm/diagnose")
async def diagnose(req: DiagnoseRequest = None):
    """Single-shot LLM analysis of current system state."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    # Gather telemetry summary from collector
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            summary = (await client.get(f"{COLLECTOR_URL}/api/summary")).json()
            failures = (await client.get(f"{ORCHESTRATOR_URL}/api/failures/state")).json()
        except Exception as e:
            raise HTTPException(503, f"could not fetch telemetry: {e}")

    user_content = (
        f"## System Summary\n```json\n{json.dumps(summary, indent=2)}\n```\n\n"
        f"## Failure Injection State\n```json\n{json.dumps(failures, indent=2)}\n```\n\n"
        f"Note: failure injection state shows what has been deliberately broken — "
        f"but you should also identify any unexplained anomalies.\n"
    )
    if req and req.extra_context:
        user_content += f"\n## Additional Context\n{req.extra_context}\n"

    user_content += "\nRespond with the JSON diagnosis described in the system prompt."

    response = await _call_claude(
        system=SYSTEM_PROMPT_CLASSIFIER,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=1500,
    )

    text = response["content"][0]["text"]
    # Try to extract JSON from response
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        diagnosis = json.loads(text[start:end]) if start >= 0 else {"raw": text}
    except json.JSONDecodeError:
        diagnosis = {"raw": text}

    return {
        "diagnosis": diagnosis,
        "telemetry_summary": summary,
        "model": CLAUDE_MODEL,
        "timestamp": time.time(),
    }


# ============================================================================
# AGENT MODE — tool-using investigation + remediation
# ============================================================================
SYSTEM_PROMPT_AGENT = """You are an autonomous SRE agent for a 5G mobile core. \
You investigate issues by calling tools, then take remediation action when confident.

You have these tools:
  • read_logs(nf, level, supi, since_seconds) — retrieve logs
  • query_metrics(nf) — get NF metric snapshot
  • get_topology() — get health of all NFs
  • list_failures() — see what failures are currently injected
  • clear_failure(nf) — clear injected failures on an NF (REMEDIATION)

Strategy:
  1. Start with get_topology() to see the big picture
  2. Look at list_failures() to see what's been injected
  3. Use query_metrics() and read_logs() to confirm hypotheses
  4. Take action with clear_failure() only when you're confident
  5. Verify the fix worked by re-checking topology/metrics

Be concise in your reasoning. Stop calling tools once you have a clear diagnosis and have remediated."""


TOOLS = [
    {
        "name": "read_logs",
        "description": "Read recent logs from an NF or across all NFs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nf": {"type": "string", "enum": ["amf", "smf", "ausf", "udm", "nrf", "upf", "pcf", "all"]},
                "level": {"type": "string", "enum": ["info", "warn", "error", "any"]},
                "since_seconds": {"type": "number", "default": 300},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["nf"],
        },
    },
    {
        "name": "query_metrics",
        "description": "Get current metric snapshot for an NF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nf": {"type": "string", "enum": ["amf", "smf", "ausf", "udm", "nrf", "upf", "pcf"]},
            },
            "required": ["nf"],
        },
    },
    {
        "name": "get_topology",
        "description": "Get current health and connectivity of all NFs.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_failures",
        "description": "List currently injected failures across all NFs.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clear_failure",
        "description": "Clear injected failures on an NF. Use this for remediation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nf": {"type": "string", "enum": ["amf", "smf", "ausf", "udm", "nrf", "upf", "pcf", "all"]},
            },
            "required": ["nf"],
        },
    },
    {
        "name": "query_error_codes",
        "description": (
            "Get a per-NF breakdown of 5G error codes emitted recently. "
            "Returns counts like {'ausf': {'AUTH_REJECTED': 47}, 'udm': {'USER_NOT_FOUND': 3}}. "
            "Use this to understand the SEMANTIC nature of failures, not just counts. "
            "Common codes you'll see: AUTH_REJECTED (RES verification failed), "
            "UE_AUTH_KEY_REVOKED (subscriber's K is revoked), USER_NOT_FOUND (SUPI unknown), "
            "ROAMING_NOT_ALLOWED, ILLEGAL_UE, DNN_NOT_SUPPORTED (unknown APN), "
            "INSUFFICIENT_RESOURCES (UPF/SMF capacity), NF_CONGESTION (overload), "
            "CONTEXT_NOT_FOUND (stale UE/session)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_subscriber_states",
        "description": (
            "Get subscriber-state counts from UDM. Subscribers can be in states like "
            "ACTIVE, BLOCKED, ROAMING_NOT_ALLOWED, AUTH_KEY_REVOKED, SUSPENDED, "
            "PROVISIONING_PENDING. Non-ACTIVE states cause UDM to return specific "
            "5G error codes when other NFs query that subscriber. If you see many "
            "AUTH_REJECTED but no fault injected on AUSF, check this — the issue "
            "may be at the subscriber level."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reset_subscribers",
        "description": (
            "Reset every subscriber back to ACTIVE state in UDM. Use when subscriber-"
            "level errors (ROAMING_NOT_ALLOWED, AUTH_KEY_REVOKED, BLOCKED) are the "
            "diagnosed cause. WARNING: this reverts ALL subscriber states, including "
            "intentionally-blocked ones — only use when the bulk-block was unintended."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "classify_failure",
        "description": (
            "Ask the ML engine to match the current error pattern against known "
            "failure scenarios. Returns ranked diagnoses with match scores and "
            "recommended remediations. Useful as a starting point for investigation. "
            "The match_score (0-1) tells you how confident the classifier is. "
            "You should still verify with read_logs and query_metrics before acting."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def _execute_tool(name: str, args: dict, client: httpx.AsyncClient) -> dict:
    """Run a tool call and return the result."""
    try:
        if name == "read_logs":
            params = {"limit": args.get("limit", 50)}
            if args.get("nf") and args["nf"] != "all":
                params["nf"] = args["nf"]
            if args.get("level") and args["level"] != "any":
                params["level"] = args["level"]
            since_s = args.get("since_seconds", 300)
            params["since"] = time.time() - since_s
            r = await client.get(f"{COLLECTOR_URL}/api/logs", params=params)
            return r.json()

        if name == "query_metrics":
            r = await client.get(f"{COLLECTOR_URL}/api/metrics/{args['nf']}",
                                  params={"window_seconds": 60})
            data = r.json()
            # Reduce to last sample for token efficiency
            history = data.get("history", [])
            return {
                "nf": args["nf"],
                "samples": len(history),
                "latest": history[-1] if history else None,
            }

        if name == "get_topology":
            r = await client.get(f"{ORCHESTRATOR_URL}/api/topology")
            return r.json()

        if name == "list_failures":
            r = await client.get(f"{ORCHESTRATOR_URL}/api/failures/state")
            return r.json()

        if name == "clear_failure":
            nf = args["nf"]
            params = {} if nf == "all" else {"nf": nf}
            r = await client.post(f"{ORCHESTRATOR_URL}/api/failures/clear", params=params)
            return r.json()

        if name == "query_error_codes":
            r = await client.get(f"{COLLECTOR_URL}/api/summary", timeout=10)
            summary = r.json()
            out = {}
            for nf, data in (summary.get("nfs") or {}).items():
                if not isinstance(data, dict):
                    continue
                codes = {}
                for k, v in data.items():
                    if isinstance(k, str) and k.startswith("errors_by_code_total"):
                        if "{" in k and "code=" in k:
                            code = k.split("code=", 1)[1].rstrip("}").strip()
                            codes[code] = codes.get(code, 0) + (v or 0)
                if codes:
                    out[nf] = codes
            return {
                "error_codes_by_nf": out,
                "total_errors": sum(c for nf in out.values() for c in nf.values()),
            }

        if name == "query_subscriber_states":
            udm_url = os.getenv("UDM_URL", "http://udm:8003")
            r = await client.get(f"{udm_url}/subscribers/state/summary", timeout=10)
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}

        if name == "reset_subscribers":
            udm_url = os.getenv("UDM_URL", "http://udm:8003")
            r = await client.post(f"{udm_url}/subscribers/state/reset", timeout=10)
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}

        if name == "classify_failure":
            ml_url = os.getenv("ML_ENGINE_URL", "http://ml_engine:9002")
            r = await client.post(f"{ml_url}/api/ml/classify-failure", timeout=20)
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}

        return {"error": f"unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e), "tool": name}


class RemediateRequest(BaseModel):
    user_goal: Optional[str] = "Investigate and fix any active issues."
    max_iterations: int = 8


@app.post("/api/llm/remediate")
async def remediate(req: RemediateRequest):
    """Agent loop: Claude calls tools, observes, acts, verifies."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    transcript = []
    messages = [{"role": "user", "content": req.user_goal}]

    async with httpx.AsyncClient(timeout=30) as client:
        for iteration in range(req.max_iterations):
            response = await _call_claude(
                system=SYSTEM_PROMPT_AGENT,
                messages=messages,
                tools=TOOLS,
                max_tokens=2000,
            )

            # Record assistant turn
            transcript.append({
                "iteration": iteration,
                "stop_reason": response.get("stop_reason"),
                "content": response["content"],
            })
            messages.append({"role": "assistant", "content": response["content"]})

            if response.get("stop_reason") != "tool_use":
                break

            # Execute all tool calls
            tool_results = []
            for block in response["content"]:
                if block["type"] == "tool_use":
                    result = await _execute_tool(block["name"], block["input"], client)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(result)[:4000],  # truncate huge results
                    })
                    transcript[-1].setdefault("tool_results", []).append({
                        "tool": block["name"],
                        "input": block["input"],
                        "result_preview": str(result)[:500],
                    })

            messages.append({"role": "user", "content": tool_results})

    return {
        "transcript": transcript,
        "iterations": len(transcript),
        "final_message": transcript[-1] if transcript else None,
    }


# ============================================================================
# CLAUDE API CLIENT
# ============================================================================
async def _call_claude(system: str, messages: list, max_tokens: int = 1500,
                       tools: Optional[list] = None) -> dict:
    """Call Anthropic API."""
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        if r.status_code != 200:
            raise HTTPException(502, f"Claude API error {r.status_code}: {r.text[:300]}")
        return r.json()
