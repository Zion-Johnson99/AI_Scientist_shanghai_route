"""Local offline HTTP API built only on http.server; never touches the network beyond loopback."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import scorer
from .metrics import SCORE_CANDIDATES_DIR, run_matrix
from .recommend import (
    InvalidRequestError,
    load_default_inputs,
    recommend,
    resolve_sha,
)
from .weights import WeightsError, weights_sha256

logger = logging.getLogger("evaluation.api")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8731
MAX_BODY_BYTES = 1_048_576


class EvaluationContext:
    """Immutable-ish bundle of inputs loaded once at server start."""

    def __init__(
        self,
        catalog: Mapping[str, Any] | None,
        dashboard: Mapping[str, Any] | None,
        access: list[Any],
        pois: Mapping[str, Any] | None,
        weights: Mapping[str, float],
        weights_sha: str,
        missing_inputs: list[str],
        metrics_write_dir: Path | None = SCORE_CANDIDATES_DIR,
    ) -> None:
        self.catalog = catalog
        self.dashboard = dashboard
        self.access = access
        self.pois = pois
        self.weights = weights
        self.weights_sha = weights_sha
        self.missing_inputs = list(missing_inputs)
        self.metrics_write_dir = metrics_write_dir
        routes = catalog.get("routes") if isinstance(catalog, Mapping) else None
        self.route_count = len(routes) if isinstance(routes, list) else 0
        cells = dashboard.get("cells") if isinstance(dashboard, Mapping) else None
        self.cell_count = len(cells) if isinstance(cells, list) else 0
        self.data_generated_at = (
            dashboard.get("data_generated_at") if isinstance(dashboard, Mapping) else None
        ) or (catalog.get("generated_at") if isinstance(catalog, Mapping) else None)
        self.status = "ok" if not self.missing_inputs else "degraded"
        self.catalog_summary: dict[str, Any] | None = None
        self.metrics_result: dict[str, Any] | None = None
        self.lock = threading.Lock()

    def health_body(self) -> dict[str, Any]:
        """Compact liveness body; must stay cheap enough to answer within 2 s."""
        body: dict[str, Any] = {
            "status": self.status,
            "service": "evaluation",
            "offline": True,
            "route_count": self.route_count,
            "cell_count": self.cell_count,
            "data_generated_at": self.data_generated_at,
            "weights_sha256": self.weights_sha,
        }
        #: Always present, so a consumer can tell "nothing missing" apart from
        #: "this build does not report the field".
        body["missing_inputs"] = list(self.missing_inputs)
        return body

    def routes_body(self) -> dict[str, Any]:
        with self.lock:
            if self.catalog_summary is None:
                self.catalog_summary = scorer.scored_catalog_summary(
                    self.catalog, self.dashboard, self.weights
                )
                self.catalog_summary["status"] = self.status
                if self.missing_inputs:
                    self.catalog_summary["missing_inputs"] = list(self.missing_inputs)
            return self.catalog_summary

    def metrics_body(self) -> dict[str, Any]:
        with self.lock:
            if self.metrics_result is None:
                self.metrics_result = run_matrix(
                    self.catalog,
                    self.dashboard,
                    self.access,
                    self.pois,
                    self.weights,
                    write_dir=self.metrics_write_dir,
                )
            return self.metrics_result


def build_context(
    metrics_write_dir: Path | None = SCORE_CANDIDATES_DIR,
) -> EvaluationContext:
    """Load every artifact once and degrade gracefully when files are missing."""
    inputs = load_default_inputs()
    try:
        weights, sha = resolve_sha(None)
    except WeightsError:
        logger.exception("weights file unavailable, falling back to documented design defaults")
        weights = {
            "environment_health": 0.30,
            "sport_match": 0.20,
            "access_convenience": 0.15,
            "route_quality": 0.20,
            "user_preference": 0.15,
        }
        sha = weights_sha256(dict(weights))
        inputs["missing_inputs"].append("default_weights.json")
    return EvaluationContext(
        inputs["catalog"],
        inputs["dashboard"],
        inputs["access"],
        inputs["pois"],
        weights,
        sha,
        inputs["missing_inputs"],
        metrics_write_dir=metrics_write_dir,
    )


class EvaluationHTTPServer(ThreadingHTTPServer):
    """Threading server that carries the shared evaluation context."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: EvaluationContext) -> None:
        super().__init__(address, EvaluationRequestHandler)
        self.context = context


class EvaluationRequestHandler(BaseHTTPRequestHandler):
    """Route /health, /routes, /metrics and POST /recommend; CORS enabled."""

    server_version = "evaluation/1.0"
    protocol_version = "HTTP/1.1"

    def _context(self) -> EvaluationContext:
        server = self.server
        if not isinstance(server, EvaluationHTTPServer):
            raise InvalidRequestError("server context unavailable")
        return server.context

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s %s", self.address_string(), format % args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        context = self._context()
        try:
            if path == "/health":
                self._send_json(200, context.health_body())
            elif path == "/routes":
                self._send_json(200, context.routes_body())
            elif path == "/metrics":
                self._send_json(200, context.metrics_body())
            else:
                self._send_json(404, {"error": "not_found", "path": path})
        except Exception as exc:
            logger.exception("GET %s failed", path)
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/recommend":
            self._send_json(404, {"error": "not_found", "path": path})
            return
        try:
            length_header = self.headers.get("Content-Length", "0")
            length = int(length_header)
            if length < 0 or length > MAX_BODY_BYTES:
                self._send_json(400, {"error": "invalid_request", "detail": "请求体长度无效"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                request = json.loads(raw.decode("utf-8")) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json(400, {"error": "invalid_request", "detail": f"JSON 解析失败: {exc}"})
                return
            if not isinstance(request, dict):
                self._send_json(400, {"error": "invalid_request", "detail": "请求体必须是 JSON 对象"})
                return
            context = self._context()
            response = recommend(
                request,
                context.catalog,
                context.dashboard,
                context.access,
                context.pois,
                context.weights,
                offline=True,
            )
            self._send_json(200, response)
        except InvalidRequestError as exc:
            self._send_json(400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:
            logger.exception("POST /recommend failed")
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})


def build_server(
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    *,
    context: EvaluationContext | None = None,
) -> EvaluationHTTPServer:
    """Create the bound server; port 0 selects a free ephemeral port."""
    active = context if context is not None else build_context()
    return EvaluationHTTPServer((host, port), active)


def serve(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> None:
    """Run the API until interrupted."""
    server = build_server(port, host)
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    logger.info("evaluation api listening on http://%s:%s", bound_host, bound_port)
    print(f"evaluation api listening on http://{bound_host}:{bound_port} (offline)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("evaluation api stopping")
    finally:
        server.server_close()
