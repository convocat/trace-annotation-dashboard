"""Flask app factory and entrypoints.

Two entry paths:
  - `trace-dashboard` CLI script → `run()` → creates app and runs it.
  - `from trace_annotator.app import create_app` → programmatic use (tests, etc).
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, render_template, request

from .cache import TraceCache
from .config import AppConfig, load_config
from .loaders.base import Loader, Trace
from .loaders.excel import ExcelLoader
from .pii.filter import PIIFilter
from .storage.annotations import Annotation, AnnotationStore


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config: AppConfig | None = None) -> Flask:
    config = config or load_config()
    loader = _build_loader(config)
    pii_filter = config.pii.build()
    annotations = AnnotationStore(config.annotations_path)
    cache = TraceCache(max_entries=config.cache_size)

    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Share wiring with routes without using globals
    app.config["loader"] = loader
    app.config["pii_filter"] = pii_filter
    app.config["annotations"] = annotations
    app.config["cache"] = cache
    app.config["project_name"] = config.project_name

    _register_routes(app)
    return app


def _build_loader(cfg: AppConfig) -> Loader:
    if cfg.source == "langfuse":
        if not cfg.langfuse.host:
            raise RuntimeError(
                "source: langfuse configured but no host set. "
                "Add 'langfuse.host' to .trace-dashboard.yml."
            )
        from .loaders.langfuse import LangfuseLoader

        return LangfuseLoader(
            host=cfg.langfuse.host,
            project_id=cfg.langfuse.project_id,
            dataset=cfg.langfuse.dataset,
            tags=cfg.langfuse.tags,
            environment=cfg.langfuse.environment,
            limit=cfg.langfuse.limit,
            tls_verify=cfg.langfuse.tls_verify,
        )

    if cfg.source == "excel":
        if not cfg.excel.path:
            raise RuntimeError(
                "source: excel configured but no path set. "
                "Add 'excel.path' to .trace-dashboard.yml."
            )
        return ExcelLoader(cfg.excel.path, cfg.excel.schemas)

    raise ValueError(f"Unknown source: {cfg.source!r}. Use 'langfuse' or 'excel'.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: Flask) -> None:

    @app.route("/")
    def index():
        return render_template("index.html", project_name=app.config["project_name"])

    @app.route("/api/traces")
    def api_traces():
        """List all trace IDs (the index shown in the sidebar)."""
        loader: Loader = app.config["loader"]
        ids = loader.list_trace_ids()
        return jsonify([{"id": tid} for tid in ids])

    @app.route("/api/traces/<trace_id>")
    def api_trace(trace_id: str):
        """Fetch one trace by ID, apply PII filter, return as JSON.

        The trace content is never written to disk here — only kept in the
        in-memory cache for the lifetime of the server process.
        """
        loader: Loader = app.config["loader"]
        cache: TraceCache = app.config["cache"]
        pii: PIIFilter = app.config["pii_filter"]

        trace = cache.get(trace_id)
        if trace is None:
            trace = loader.get(trace_id)
            if trace is None:
                return jsonify({"error": "not_found"}), 404
            cache.put(trace)

        return jsonify(_trace_to_json(trace, pii))

    @app.route("/api/annotations")
    def api_annotations():
        store: AnnotationStore = app.config["annotations"]
        return jsonify({tid: ann.to_dict() for tid, ann in store.load_all().items()})

    @app.route("/api/annotate", methods=["POST"])
    def api_annotate():
        payload = request.get_json(force=True)
        store: AnnotationStore = app.config["annotations"]
        ann = Annotation(
            trace_id=str(payload.get("trace_id", "")),
            project=str(payload.get("project", "")),
            source=str(payload.get("source", "")),
            question_excerpt=str(payload.get("question_excerpt", "")),
            answer_excerpt=str(payload.get("answer_excerpt", "")),
            pass_fail=str(payload.get("pass_fail", "")),
            note=str(payload.get("note", "")),
            category=str(payload.get("category", "")),
            action=str(payload.get("action", "")),
            response=str(payload.get("response", "")),
        )
        if not ann.trace_id:
            return jsonify({"error": "missing trace_id"}), 400
        store.save(ann)
        return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _trace_to_json(trace: Trace, pii: PIIFilter) -> dict:
    """Serialise one trace for the UI with PII scrubbed on the way out.

    Message bodies, sources, and context values are all run through the filter.
    Metadata keys (field names) are left alone — only values are scrubbed.
    """
    return {
        "id": trace.id,
        "messages": [
            {
                "role": m.role,
                "content": pii.scrub(m.content),
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in trace.messages
        ],
        "sources": [pii.scrub(s) for s in trace.sources],
        "metadata": _scrub_metadata(trace.metadata, pii),
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def _scrub_metadata(meta: dict, pii: PIIFilter) -> dict:
    out: dict = {}
    for k, v in meta.items():
        if isinstance(v, str):
            out[k] = pii.scrub(v)
        elif isinstance(v, dict):
            out[k] = {sk: (pii.scrub(sv) if isinstance(sv, str) else sv) for sk, sv in v.items()}
        elif isinstance(v, list):
            out[k] = [pii.scrub(item) if isinstance(item, str) else item for item in v]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run() -> int:
    """`trace-dashboard` CLI entrypoint."""
    try:
        cfg = load_config()
        app = create_app(cfg)
    except Exception as e:
        print(f"Failed to start: {e}", file=sys.stderr)
        return 1

    url = f"http://{cfg.host}:{cfg.port}"
    print(f"Project:      {cfg.project_name}")
    print(f"Source:       {cfg.source}")
    print(f"Annotations:  {cfg.annotations_path}")
    print(f"Dashboard:    {url}")
    print()
    if cfg.open_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(run())
