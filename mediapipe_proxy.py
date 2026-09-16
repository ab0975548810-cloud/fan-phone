"""Same-origin MediaPipe asset proxy for the guided AI-head tool.

The storefront CSP intentionally limits browser network access to self.  Serving
MediaPipe's ESM, WASM loader/binary and MagicTouch model through Flask keeps the
browser on fanphone.zeabur.app while the server fetches pinned upstream assets.
"""
from __future__ import annotations

import re

from flask import Response, abort

_INSTALLED = False
_VERSION = "1.0.1"
_ALLOWED_WASM = {
    "vision_wasm_internal.js": "application/javascript; charset=utf-8",
    "vision_wasm_internal.wasm": "application/wasm",
    "vision_wasm_nosimd_internal.js": "application/javascript; charset=utf-8",
    "vision_wasm_nosimd_internal.wasm": "application/wasm",
    "vision_wasm_module_internal.js": "application/javascript; charset=utf-8",
    "vision_wasm_module_internal.wasm": "application/wasm",
}

_BUNDLE_SOURCES = (
    f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{_VERSION}/vision_bundle.mjs",
    f"https://unpkg.com/@mediapipe/tasks-vision@{_VERSION}/vision_bundle.mjs",
)
_MODEL_SOURCES = (
    "https://storage.googleapis.com/mediapipe-models/interactive_segmenter_v2/magic_touch/int8/latest/interactive_segmentation.task",
    "https://storage.googleapis.com/mediapipe-models/interactive_segmenter_v2/magic_touch/int8/1/interactive_segmentation.task",
)


def _wasm_sources(filename: str):
    return (
        f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{_VERSION}/wasm/{filename}",
        f"https://unpkg.com/@mediapipe/tasks-vision@{_VERSION}/wasm/{filename}",
    )


def _fetch_bytes(app_module, urls, *, max_bytes: int):
    if not app_module.requests:
        raise RuntimeError("requests 套件未載入")
    last_error = None
    headers = {"User-Agent": "Benfuwan-MediaPipe-Proxy/1.0"}
    for url in urls:
        try:
            resp = app_module.requests.get(url, headers=headers, timeout=(8, 90))
            if not (200 <= resp.status_code < 300):
                last_error = RuntimeError(f"upstream HTTP {resp.status_code}")
                continue
            body = resp.content
            if not body:
                last_error = RuntimeError("upstream empty body")
                continue
            if len(body) > max_bytes:
                last_error = RuntimeError(f"upstream asset too large: {len(body)}")
                continue
            return body, url
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"MediaPipe upstream unavailable: {last_error}")


def _asset_response(body: bytes, content_type: str, source: str):
    resp = Response(body, status=200, content_type=content_type)
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    resp.headers["X-Benfuwan-MediaPipe"] = "same-origin-proxy"
    resp.headers["X-Benfuwan-Upstream"] = "jsdelivr" if "jsdelivr" in source else ("unpkg" if "unpkg" in source else "google")
    return resp


def _allow_wasm_csp(resp):
    """MediaPipe compiles WebAssembly in the page; modern CSP needs wasm-unsafe-eval."""
    csp = resp.headers.get("Content-Security-Policy") or ""
    if not csp:
        return resp
    parts = [part.strip() for part in csp.split(";") if part.strip()]
    out = []
    changed = False
    for part in parts:
        if part.startswith("script-src "):
            if "'wasm-unsafe-eval'" not in part:
                part += " 'wasm-unsafe-eval'"
                changed = True
        out.append(part)
    if changed:
        resp.headers["Content-Security-Policy"] = "; ".join(out)
    return resp


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app

    @app.route("/vendor/mediapipe/vision_bundle.mjs", methods=["GET"])
    def mediapipe_bundle():
        try:
            body, source = _fetch_bytes(app_module, _BUNDLE_SOURCES, max_bytes=2 * 1024 * 1024)
            head = body[:256].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                raise RuntimeError("MediaPipe bundle upstream returned HTML")
            return _asset_response(body, "application/javascript; charset=utf-8", source)
        except Exception as exc:
            print("[MEDIAPIPE] bundle proxy failed:", repr(exc), flush=True)
            return Response("MediaPipe bundle unavailable", status=502, content_type="text/plain; charset=utf-8")

    @app.route("/vendor/mediapipe/wasm/<path:filename>", methods=["GET"])
    def mediapipe_wasm(filename):
        if filename not in _ALLOWED_WASM or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
            abort(404)
        try:
            body, source = _fetch_bytes(app_module, _wasm_sources(filename), max_bytes=32 * 1024 * 1024)
            if filename.endswith(".wasm") and not body.startswith(b"\x00asm"):
                raise RuntimeError("invalid wasm magic")
            return _asset_response(body, _ALLOWED_WASM[filename], source)
        except Exception as exc:
            print("[MEDIAPIPE] wasm proxy failed:", filename, repr(exc), flush=True)
            return Response("MediaPipe WASM unavailable", status=502, content_type="text/plain; charset=utf-8")

    @app.route("/vendor/mediapipe/interactive_segmentation.task", methods=["GET"])
    def mediapipe_interactive_model():
        try:
            body, source = _fetch_bytes(app_module, _MODEL_SOURCES, max_bytes=64 * 1024 * 1024)
            return _asset_response(body, "application/octet-stream", source)
        except Exception as exc:
            print("[MEDIAPIPE] model proxy failed:", repr(exc), flush=True)
            return Response("MediaPipe model unavailable", status=502, content_type="text/plain; charset=utf-8")

    app.after_request(_allow_wasm_csp)
    print("[MEDIAPIPE] same-origin asset proxy installed", flush=True)
