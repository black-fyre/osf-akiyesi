"""Verification desk UI + ingest HTTP endpoints (CLAUDE.md components 1 & 5).

Server-side templates only, no React, no JS framework, per CLAUDE.md's
stack note ("optimize for demo reliability over elegance"). Built on
`http.server` (standard library) rather than FastAPI: this iteration was
built in a sandbox with no package-registry access (see docs/ai-usage.md),
so app/ has no third-party web-framework dependency. See main_fastapi.py
for the Cloud Run deployment entrypoint this is designed to be swapped for.

Routes:
  GET  /                                    landing page
  POST /webhook/sms                         real SMS provider webhook (JSON)
  POST /simulate/inbound                    demo-reliability endpoint (form or JSON)
  GET  /desk?community=<id>                 security committee: normal-channel clusters only
  GET  /desk/cluster?community=<id>&pattern=<id>   referral brief + escalate action
  POST /desk/escalate                       records an audit_log entry
  GET  /desk/audit?community=<id>           audit trail
  GET  /protected-outbox?community=<id>     landlord association's separate inbox
  GET  /healthz                             liveness check
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import audit, clustering, ingest, referral
from app.config import AppConfig, get_config
from app.llm import LLMClient, get_llm_client
from app.storage import Store, make_store

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _age_str(dt: datetime) -> str:
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "under an hour ago"
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours // 24)}d ago"


_jinja_env.filters["age"] = _age_str
_jinja_env.filters["date_only"] = lambda dt: dt.date().isoformat()


def render(template_name: str, **context: Any) -> bytes:
    template = _jinja_env.get_template(template_name)
    return template.render(**context).encode("utf-8")


class AppContext:
    """Bundles the process-wide config/llm/store so the request handler
    (which http.server instantiates per-connection) can share them.
    """

    def __init__(self, config: Optional[AppConfig] = None, llm: Optional[LLMClient] = None, store: Optional[Store] = None):
        self.config = config or get_config()
        self.llm = llm or get_llm_client()
        self.store = store or make_store(":memory:")
        self.lock = threading.Lock()


def make_handler(ctx: AppContext):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Akiyesi/0.1"

        def log_message(self, fmt, *args):  # quieter test/demo output
            pass

        # -- helpers --
        def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, obj: Dict[str, Any]):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(length) if length else b""

        def _parsed_form_or_json(self) -> Dict[str, Any]:
            raw = self._read_body()
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return json.loads(raw or b"{}")
            fields = parse_qs(raw.decode("utf-8"))
            return {k: v[0] for k, v in fields.items()}

        def _community_or_400(self, qs: Dict[str, list]):
            community_id = (qs.get("community") or [None])[0]
            if community_id is None:
                # default to the first configured community for a one-click demo
                community_id = next(iter(ctx.config.communities))
            community = ctx.config.community_by_id(community_id)
            return community

        # -- routing --
        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            path = parsed.path

            if path == "/healthz":
                return self._send_json(200, {"ok": True})

            if path == "/":
                return self._send(200, render("index.html", communities=ctx.config.communities.values()))

            if path == "/desk":
                return self._desk_list(qs)

            if path == "/desk/cluster":
                return self._desk_cluster_detail(qs)

            if path == "/desk/audit":
                return self._desk_audit(qs)

            if path == "/protected-outbox":
                return self._protected_outbox(qs)

            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/webhook/sms":
                return self._handle_ingest()

            if path == "/simulate/inbound":
                return self._handle_ingest()

            if path == "/desk/escalate":
                return self._handle_escalate()

            if path == "/desk/protected-escalate":
                return self._handle_protected_escalate()

            if path == "/ingest/retry":
                recovered = ingest.retry_pending(ctx.config, ctx.llm, ctx.store)
                return self._send_json(200, {"recovered": len(recovered)})

            return self._send(404, b"not found", "text/plain")

        # -- handlers --
        def _handle_ingest(self):
            payload = self._parsed_form_or_json()
            with ctx.lock:
                report = ingest.receive_webhook(payload, ctx.config, ctx.llm, ctx.store)
            if report is None:
                return self._send_json(202, {"accepted": True, "processed": False, "note": "logged, will be retried"})
            return self._send_json(
                200,
                {
                    "accepted": True,
                    "processed": True,
                    "report_id": report.id,
                    "status": report.status,
                    "channel": report.channel,
                    "pattern_id": report.pattern_id,
                },
            )

        def _desk_list(self, qs):
            community = self._community_or_400(qs)
            if community is None:
                return self._send(404, b"unknown community", "text/plain")
            with ctx.lock:
                reports = ctx.store.reports_for_community(community.id, channel="normal")
                already = {
                    e.pattern_id: e.decided_at
                    for e in ctx.store.audit_log_for_community(community.id)
                    if e.action == "escalate"
                }
                clusters = clustering.compute_clusters(reports, community, already_escalated=already)
            return self._send(200, render("desk_list.html", community=community, clusters=clusters, communities=ctx.config.communities.values()))

        def _desk_cluster_detail(self, qs):
            community = self._community_or_400(qs)
            pattern_id = (qs.get("pattern") or [None])[0]
            if community is None or pattern_id is None:
                return self._send(400, b"missing community or pattern", "text/plain")
            with ctx.lock:
                reports = ctx.store.reports_for_community(community.id, channel="normal")
                already = {
                    e.pattern_id: e.decided_at
                    for e in ctx.store.audit_log_for_community(community.id)
                    if e.action == "escalate"
                }
                clusters = clustering.compute_clusters(reports, community, already_escalated=already)
            match = next((c for c in clusters if c.pattern_id == pattern_id), None)
            if match is None:
                return self._send(404, b"cluster not found", "text/plain")
            brief = referral.build_cluster_referral_brief(match, reports, community)
            return self._send(200, render("desk_cluster_detail.html", community=community, cluster=match, brief=brief))

        def _handle_escalate(self):
            form = self._parsed_form_or_json()
            community = ctx.config.community_by_id(form.get("community_id", ""))
            pattern_id = form.get("pattern_id")
            decided_by = form.get("decided_by") or "desk-user"
            if community is None or not pattern_id:
                return self._send(400, b"missing community_id or pattern_id", "text/plain")
            with ctx.lock:
                reports = ctx.store.reports_for_community(community.id, channel="normal")
                already = {
                    e.pattern_id: e.decided_at
                    for e in ctx.store.audit_log_for_community(community.id)
                    if e.action == "escalate"
                }
                clusters = clustering.compute_clusters(reports, community, already_escalated=already)
                match = next((c for c in clusters if c.pattern_id == pattern_id), None)
                if match is None:
                    return self._send(404, b"cluster not found", "text/plain")
                if match.status != clustering.STATUS_ESCALATE_READY:
                    return self._send_json(409, {"error": f"cluster status is {match.status}, not escalate_ready"})
                brief = referral.build_cluster_referral_brief(match, reports, community)
                audit.record_escalation(
                    ctx.store,
                    community_id=community.id,
                    pattern_id=pattern_id,
                    channel="normal",
                    action="escalate",
                    decided_by=decided_by,
                    evidence_report_ids=match.report_ids,
                    referral_brief=brief,
                    profiling_guard_redacted_fraction=match.profiling.redacted_fraction,
                )
            self.send_response(303)
            self.send_header("Location", f"/desk?community={community.id}")
            self.end_headers()

        def _handle_protected_escalate(self):
            form = self._parsed_form_or_json()
            community = ctx.config.community_by_id(form.get("community_id", ""))
            report_id = form.get("report_id")
            decided_by = form.get("decided_by") or "landlord-association"
            if community is None or not report_id:
                return self._send(400, b"missing community_id or report_id", "text/plain")
            with ctx.lock:
                reports = ctx.store.reports_for_community(community.id, channel="protected")
                already = {
                    e.evidence_report_ids[0]: e.decided_at
                    for e in ctx.store.audit_log_for_community(community.id)
                    if e.action == "protected_escalate"
                }
                items = clustering.protected_items(reports, community, already_escalated_report_ids=already)
                match = next((i for i in items if i.report.id == report_id), None)
                if match is None:
                    return self._send(404, b"protected report not found", "text/plain")
                if match.status != clustering.PROTECTED_READY:
                    return self._send_json(409, {"error": f"protected item status is {match.status}"})
                brief = referral.build_protected_referral_brief(match, community)
                audit.record_escalation(
                    ctx.store,
                    community_id=community.id,
                    pattern_id=match.report.pattern_id,
                    channel="protected",
                    action="protected_escalate",
                    decided_by=decided_by,
                    evidence_report_ids=[match.report.id],
                    referral_brief=brief,
                    profiling_guard_redacted_fraction=match.profiling.redacted_fraction,
                )
            self.send_response(303)
            self.send_header("Location", f"/protected-outbox?community={community.id}")
            self.end_headers()

        def _desk_audit(self, qs):
            community = self._community_or_400(qs)
            if community is None:
                return self._send(404, b"unknown community", "text/plain")
            with ctx.lock:
                entries = ctx.store.audit_log_for_community(community.id)
                # The desk audit view is for the *security committee's own*
                # normal-channel decisions; protected escalations are the
                # landlord association's business, not the desk's, so they
                # are filtered out here even though they share the table.
                entries = [e for e in entries if e.channel == "normal"]
            return self._send(200, render("audit_log.html", community=community, entries=entries))

        def _protected_outbox(self, qs):
            community = self._community_or_400(qs)
            if community is None:
                return self._send(404, b"unknown community", "text/plain")
            with ctx.lock:
                reports = ctx.store.reports_for_community(community.id, channel="protected")
                already = {
                    e.evidence_report_ids[0]: e.decided_at
                    for e in ctx.store.audit_log_for_community(community.id)
                    if e.action == "protected_escalate"
                }
                items = clustering.protected_items(reports, community, already_escalated_report_ids=already)
            return self._send(200, render("protected_outbox.html", community=community, items=items))

    return Handler


def run(host: str = "127.0.0.1", port: int = 8000, db_path: str = "data/akiyesi.db") -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ctx = AppContext(store=make_store(db_path))
    handler = make_handler(ctx)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Akiyesi desk running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
