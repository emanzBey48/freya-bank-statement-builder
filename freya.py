"""Thin client for the Freya API. Standard library only.

    export FREYA_API_KEY=fak_...            # your workspace key
    export FREYA_API_URL=https://staging-app.freyavoice.ai   # default
"""
import json, os, pathlib, time, urllib.request, urllib.error, urllib.parse

# Auto-load from env.sh or .env or set_env.bat if not set
if not os.environ.get("FREYA_API_KEY"):
    for env_name in ("env.sh", ".env", "set_env.bat"):
        env_p = pathlib.Path(__file__).parent / env_name
        if env_p.exists():
            for line in env_p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("export "): line = line[7:].strip()
                if line.startswith("set "): line = line[4:].strip()
                if "=" in line and not line.startswith("#") and not line.startswith("::"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().split("#")[0].strip().strip('"').strip("'")
                    if v and "BURAYA" not in v and k not in os.environ:
                        os.environ[k] = v

URL = os.environ.get("FREYA_API_URL", "https://staging-app.freyavoice.ai")
# Cloudflare rejects requests without a browser-like User-Agent (error 1010).
HEADERS = {"Authorization": "Bearer " + os.environ.get("FREYA_API_KEY", ""), "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (build-the-builder)"}

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 522, 524}   # the platform is busy, not broken

def api(method, path, body=None, **params):
    """Call the API and return the `result` part of its {success, data: {message, result}} envelope.

    A busy platform answers 503 now and then. A build must not die on that, so
    those answers are repeated with a back-off; a 400 is a real error and stops."""
    q = "?" + urllib.parse.urlencode(params) if params else ""
    last_err = None
    # Keep transient API failures bounded. Long backoffs made a failed status
    # endpoint hold the case runner for many minutes; simulation state is also
    # recovered through the workspace list in run_simulation.
    for attempt in range(4):
        req = urllib.request.Request(URL + path + q, data=json.dumps(body).encode() if body is not None else None, headers=HEADERS, method=method)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.load(r)
                return out.get("data", {}).get("result", out) if isinstance(out, dict) else out
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:1500]
            if e.code in RETRY_STATUS and attempt < 3:
                wait = 10
                print(f"  [retry] {method} {path} -> {e.code}, waiting {wait}s (attempt {attempt + 1}/3 retries)", flush=True)
                time.sleep(wait)
                last_err = RuntimeError(f"{method} {path} -> {e.code}: {detail}")
                continue
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None
        except Exception as e:
            last_err = e
            if attempt < 3:
                print(f"  [retry] {method} {path} -> {last_err}, waiting 10s (attempt {attempt + 1}/3 retries)", flush=True)
                time.sleep(10)
    raise RuntimeError(f"{method} {path} failed after 4 attempts: {last_err}") from None

_ws = None
def workspace_id():
    """The workspace your key belongs to. List routes need it as a query parameter."""
    global _ws
    if not _ws:
        r = api("GET", "/api/v2/workspaces"); items = r.get("workspaces") or r.get("items") or r
        _ws = os.environ.get("FREYA_WORKSPACE_ID") or items[0]["id"]
    return _ws

def create_workflow(name, workflow):
    """Create a workflow. Freya creates its agent with it. Returns {workflow_id, agent_id}."""
    w = api("POST", "/api/v2/workflow", {"name": name, "workflow": workflow})["workflow"]
    return {"workflow_id": w["id"], "agent_id": w["agentId"]}

def save_workflow(slot, workflow, state_file=".freya-agents.json"):
    """Create the workflow the first time, update the same one afterwards. Use this in your builder.

    `slot` is your own label, for example the brief's file name. A workspace holds a limited number of workflows,
    so a builder that creates a new one on every run stops working after a few runs."""
    import pathlib
    f = pathlib.Path(state_file); state = json.loads(f.read_text()) if f.exists() else {}
    if slot in state:
        state[slot]["version"] = update_workflow(state[slot]["workflow_id"], workflow); f.write_text(json.dumps(state, indent=1))
    else:
        state[slot] = create_workflow(f"{slot} {time.strftime('%m%d-%H%M%S')}", workflow); f.write_text(json.dumps(state, indent=1))
    return state[slot]
def validate_workflow(name, workflow): return api("POST", "/api/v2/workflow", {"name": name, "workflow": workflow}, dryRun="true")
def update_workflow(workflow_id, workflow):
    """Update a workflow and publish the new version. Returns the published version number.

    An update alone only saves a new, unpublished version. Simulations and calls keep running the published one,
    so an update that is not published tests your old phone agent."""
    api("PUT", f"/api/v2/workflow/{workflow_id}", {"workflow": workflow})
    # The platform fills in a default agent_config. If its model is not the event's model, a simulation still runs
    # (it overrides the model), but a chat turn or a real call cannot start. Set the model and save once more.
    w = api("GET", f"/api/v2/workflow/{workflow_id}", workspaceId=workspace_id())["workflow"]["workflow"]
    ac = w.get("agent_config") or {}; llm = ac.get("llmConfig") or {}
    if (llm.get("provider"), llm.get("model")) != (AGENT_LLM["provider"], AGENT_LLM["model"]):
        ac["llmConfig"] = {**llm, **AGENT_LLM}; api("PUT", f"/api/v2/workflow/{workflow_id}", {"workflow": {**w, "agent_config": ac}})
    vs = api("GET", f"/api/v2/versions/workflow/{workflow_id}", workspaceId=workspace_id())["versions"]
    newest = max(vs, key=lambda v: v["versionNumber"])
    if not newest.get("isPublished"): api("POST", f"/api/v2/versions/workflow/{workflow_id}/publish", {"versionId": newest["id"]})
    return newest["versionNumber"]
def export_workflow(workflow_id, path):
    """Write the workflow as it is on the platform to a file. This file is part of what you submit."""
    w = api("GET", f"/api/v2/workflow/{workflow_id}", workspaceId=workspace_id())["workflow"]
    open(path, "w").write(json.dumps({"workflow_id": w["id"], "agent_id": w.get("agentId"), "updated_at": w.get("updatedAt"), "workflow": w["workflow"]}, indent=1)); return path
def create_personas(personas):        return api("POST", "/api/v2/personas", {"personas": personas})
def get_iteration(sim_id, it_id):
    """One iteration with ALL its runs. The route returns 30 runs by default and 100 at most, so this reads page by page."""
    out, off = None, 0
    while True:
        r = api("GET", f"/api/v2/simulations/{sim_id}/iterations/{it_id}", limit=100, offset=off)
        if out is None: out = r
        else: out["runs"] += r["runs"]
        off += 100
        if len(r["runs"]) < 100: return out
def get_call(call_id):
    """One simulated call: `messages` holds the transcript, tool calls included. Run ids and call ids come from get_iteration()['runs']."""
    return api("GET", f"/api/v2/call/{call_id}")["call"]

def list_simulations(limit=10):
    """Recent simulations in this workspace; the workspace runs only one at a time."""
    r = api("GET", "/api/v2/simulations", workspaceId=workspace_id(), limit=limit)
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for key in ("simulations", "items", "data"):
            if isinstance(r.get(key), list):
                return r[key]
    return []

def cancel_simulation(sim_id):
    """Cancel a known stuck simulation when the operator explicitly requests it."""
    return api("POST", f"/api/v2/simulations/{sim_id}/cancel", {})

# The model every team's phone agent runs on: Freya's model on the event's own GPU box. Do not change it. (Organisers can point a test at another model with the two variables.)
AGENT_LLM = {"provider": os.environ.get("FREYA_AGENT_PROVIDER", "experimental-5"), "model": os.environ.get("FREYA_AGENT_MODEL", "experimental-5")}
SIM_LLM = {"provider": "google", "model": "gemini-3-flash-preview"}        # plays the customer and judges

def run_simulation(agent_id, name, variables_by_persona, max_seconds=420,
                   concurrency=int(os.environ.get("FREYA_SIM_CONCURRENCY", "5")), wait_limit=1500):
    """Start a text simulation, wait for it, return (simulation_id, iteration_id).

    A workspace runs one simulation at a time, so a start waits for the running one.
    A busy platform can also leave a simulation 'running' far longer than one call:
    after wait_limit seconds the state so far is returned instead of waiting for
    ever, so a build never hangs.
    """
    # Surface existing workspace work before starting. Do not silently cancel it:
    # it may still be making progress after a transient chat/API 5xx.
    waited_for_workspace = 0
    while True:
        active = [s for s in list_simulations(10)
                  if str(s.get("status", "")).lower() in ("running", "queued", "pending")]
        if not active:
            break
        ids = ", ".join(str(s.get("id", "?")) for s in active)
        print(f"workspace already has active simulation(s) {ids}; checking again in 10s", flush=True)
        time.sleep(10)
        waited_for_workspace += 10
        if waited_for_workspace >= wait_limit:
            raise RuntimeError("workspace still has active simulation(s) after "
                               f"{waited_for_workspace}s: {ids}; inspect GET /api/v2/simulations?limit=10 "
                               "and cancel a confirmed-stuck run explicitly")

    while True:
        try:
            sim = api("POST", "/api/v2/simulations", {
                "agentId": agent_id, "name": name, "mode": "chat", "selectedPersonaIds": list(variables_by_persona),
                "customerVariablesMap": variables_by_persona, "maxConcurrentCalls": concurrency, "runsPerPersona": 1, "maxCallDurationSeconds": max_seconds,
                "assistantLlmOverride": AGENT_LLM, "routingLlmOverride": AGENT_LLM, "extractionLlmOverride": AGENT_LLM,
                "personaLlmOverride": SIM_LLM, "analysisLlmOverride": SIM_LLM})
            break
        except RuntimeError as e:
            if "concurrent simulations" not in str(e): raise
            print("another simulation is running in this workspace, waiting 30 s", flush=True); time.sleep(30)
    sim_id = (sim.get("simulation") or sim)["id"]
    waited = 0
    while True:
        time.sleep(10); waited += 10
        try:
            s = api("GET", f"/api/v2/simulations/{sim_id}"); s = s.get("simulation") or s
        except RuntimeError as exc:
            # The item endpoint has intermittently returned 504 while the
            # workspace list remained available and showed the true status.
            print(f"simulation detail unavailable ({exc}); checking workspace list", flush=True)
            match = next((x for x in list_simulations(10) if str(x.get("id")) == str(sim_id)), None)
            if match is None:
                if waited >= wait_limit:
                    raise RuntimeError(f"could not read status for simulation {sim_id}; last error: {exc}") from None
                continue
            s = match
        if s.get("status") in ("completed", "failed", "paused"): break
        if waited >= wait_limit:
            print(f"simulation {sim_id} is still '{s.get('status')}' after {waited} s; reading what is there", flush=True)
            break
    its = api("GET", f"/api/v2/simulations/{sim_id}/iterations"); its = its.get("iterations") or its.get("items") or its
    return sim_id, its[0]["id"], s.get("status")
