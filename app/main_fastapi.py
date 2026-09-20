"""FastAPI entrypoint for the Cloud Run deployment CLAUDE.md specifies.

NOT exercised in this iteration: the sandbox this repo was built in has no
package-registry access, so fastapi/uvicorn could not be installed to run
or test this file (see docs/ai-usage.md). It is included because CLAUDE.md
names FastAPI + Cloud Run as the target stack, and because the actual
tested-and-passing implementation is app/server.py (standard-library
http.server) -- this file is a thin routing layer over the exact same
app.pipeline / app.ingest / app.clustering / app.referral / app.audit
modules those tests already cover, so the risk surface here is small and
mechanical (HTTP plumbing), not business logic.

To run for real, on a machine with network access:
    pip install -r requirements.txt
    uvicorn app.main_fastapi:app --host 0.0.0.0 --port 8080

Before treating this as production-ready, at minimum: verify it actually
boots and serves under uvicorn (untested here), add webhook signature
verification for whichever SMS provider is configured (see
.env.example -- there is none yet, in either this file or app/server.py),
and switch app/storage.py's Store to the documented FirestoreStore.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import audit, clustering, ingest, referral
from app.config import get_config
from app.llm import get_llm_client
from app.server import _age_str  # reuse the same "3h ago" formatting as app/server.py
from app.storage import make_store

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Àkíyèsí")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["age"] = _age_str
templates.env.filters["date_only"] = lambda dt: dt.date().isoformat()

config = get_config()
llm = get_llm_client()
store = make_store(":memory:")  # swap for FirestoreStore in production; see app/storage.py


@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}


async def _ingest(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload: Dict[str, Any] = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    report = ingest.receive_webhook(payload, config, llm, store)
    if report is None:
        return JSONResponse({"accepted": True, "processed": False, "note": "logged, will be retried"}, status_code=202)
    return JSONResponse({
        "accepted": True,
        "processed": True,
        "report_id": report.id,
        "status": report.status,
        "channel": report.channel,
        "pattern_id": report.pattern_id,
    })


@app.post("/webhook/sms")
async def webhook_sms(request: Request) -> JSONResponse:
    return await _ingest(request)


@app.post("/simulate/inbound")
async def simulate_inbound(request: Request) -> JSONResponse:
    return await _ingest(request)


@app.post("/ingest/retry")
def ingest_retry() -> Dict[str, int]:
    recovered = ingest.retry_pending(config, llm, store)
    return {"recovered": len(recovered)}


def _already_escalated(community_id: str) -> Dict[str, Any]:
    return {
        e.pattern_id: e.decided_at
        for e in store.audit_log_for_community(community_id)
        if e.action == "escalate"
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "communities": config.communities.values()})


@app.get("/desk", response_class=HTMLResponse)
def desk_list(request: Request, community: Optional[str] = None) -> HTMLResponse:
    community_id = community or next(iter(config.communities))
    c = config.community_by_id(community_id)
    if c is None:
        return HTMLResponse("unknown community", status_code=404)
    reports = store.reports_for_community(c.id, channel="normal")
    clusters = clustering.compute_clusters(reports, c, already_escalated=_already_escalated(c.id), patterns=config.patterns)
    return templates.TemplateResponse(
        "desk_list.html", {"request": request, "community": c, "clusters": clusters, "communities": config.communities.values()}
    )


@app.get("/desk/cluster", response_class=HTMLResponse)
def desk_cluster_detail(request: Request, community: str, pattern: str) -> HTMLResponse:
    c = config.community_by_id(community)
    if c is None:
        return HTMLResponse("unknown community", status_code=404)
    reports = store.reports_for_community(c.id, channel="normal")
    clusters = clustering.compute_clusters(reports, c, already_escalated=_already_escalated(c.id), patterns=config.patterns)
    match = next((cl for cl in clusters if cl.pattern_id == pattern), None)
    if match is None:
        return HTMLResponse("cluster not found", status_code=404)
    brief = referral.build_cluster_referral_brief(match, reports, c)
    return templates.TemplateResponse("desk_cluster_detail.html", {"request": request, "community": c, "cluster": match, "brief": brief})


@app.post("/desk/escalate")
def desk_escalate(community_id: str = Form(...), pattern_id: str = Form(...), decided_by: str = Form("desk-user")):
    c = config.community_by_id(community_id)
    if c is None:
        return JSONResponse({"error": "unknown community"}, status_code=404)
    reports = store.reports_for_community(c.id, channel="normal")
    clusters = clustering.compute_clusters(reports, c, already_escalated=_already_escalated(c.id), patterns=config.patterns)
    match = next((cl for cl in clusters if cl.pattern_id == pattern_id), None)
    if match is None:
        return JSONResponse({"error": "cluster not found"}, status_code=404)
    if match.status != clustering.STATUS_ESCALATE_READY:
        return JSONResponse({"error": f"cluster status is {match.status}, not escalate_ready"}, status_code=409)
    brief = referral.build_cluster_referral_brief(match, reports, c)
    audit.record_escalation(
        store, community_id=c.id, pattern_id=pattern_id, channel="normal", action="escalate",
        decided_by=decided_by, evidence_report_ids=match.report_ids, referral_brief=brief,
        profiling_guard_redacted_fraction=match.profiling.redacted_fraction,
    )
    return RedirectResponse(url=f"/desk?community={c.id}", status_code=303)


@app.get("/desk/audit", response_class=HTMLResponse)
def desk_audit(request: Request, community: str) -> HTMLResponse:
    c = config.community_by_id(community)
    if c is None:
        return HTMLResponse("unknown community", status_code=404)
    entries = [e for e in store.audit_log_for_community(c.id) if e.channel == "normal"]
    return templates.TemplateResponse("audit_log.html", {"request": request, "community": c, "entries": entries})


@app.get("/protected-outbox", response_class=HTMLResponse)
def protected_outbox(request: Request, community: str) -> HTMLResponse:
    c = config.community_by_id(community)
    if c is None:
        return HTMLResponse("unknown community", status_code=404)
    reports = store.reports_for_community(c.id, channel="protected")
    already = {
        e.evidence_report_ids[0]: e.decided_at
        for e in store.audit_log_for_community(c.id)
        if e.action == "protected_escalate"
    }
    items = clustering.protected_items(reports, c, already_escalated_report_ids=already)
    return templates.TemplateResponse("protected_outbox.html", {"request": request, "community": c, "items": items})
