"""Small resilience layer for intermittent Supabase/PostgREST PGRST303 failures.

Supabase has an ongoing class of incidents where PostgREST can reject a freshly
minted internal JWT as "issued at future".  This module only retries that exact
error and keeps a short in-process last-good cache for read-only admin/config
requests.  It does not hide unrelated database errors.
"""
from __future__ import annotations

import copy
import functools
import threading
import time

from flask import Response

_INSTALLED = False
_LOCK = threading.RLock()
_LAST_JSON = {}          # key -> (monotonic_ts, python_value)
_LAST_RESPONSE = {}      # endpoint -> (monotonic_ts, status, headers, body)
_RETRY_DELAYS = (0.8, 1.6)
_STALE_SECONDS = 15 * 60


def _is_future_jwt(value) -> bool:
    text = str(value or '').lower()
    return 'pgrst303' in text and 'jwt issued at future' in text


def _remember_json(key, value):
    try:
        snapshot = copy.deepcopy(value)
    except Exception:
        snapshot = value
    with _LOCK:
        _LAST_JSON[str(key)] = (time.monotonic(), snapshot)


def _stale_json(key):
    with _LOCK:
        item = _LAST_JSON.get(str(key))
    if not item:
        return None
    ts, value = item
    if time.monotonic() - ts > _STALE_SECONDS:
        return None
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _remember_response(endpoint, resp):
    if not isinstance(resp, Response) or not (200 <= resp.status_code < 300):
        return
    try:
        headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in ('content-length', 'set-cookie')]
        body = resp.get_data()
        with _LOCK:
            _LAST_RESPONSE[endpoint] = (time.monotonic(), resp.status_code, headers, body)
    except Exception:
        pass


def _stale_response(endpoint):
    with _LOCK:
        item = _LAST_RESPONSE.get(endpoint)
    if not item:
        return None
    ts, status, headers, body = item
    if time.monotonic() - ts > _STALE_SECONDS:
        return None
    resp = Response(body, status=status)
    for k, v in headers:
        resp.headers[k] = v
    resp.headers['X-Benfuwan-Stale'] = '1'
    resp.headers['Warning'] = '110 - "Response is temporarily served from last known good data"'
    return resp


def _response_has_future_jwt(resp) -> bool:
    try:
        if isinstance(resp, Response):
            return resp.status_code >= 400 and _is_future_jwt(resp.get_data(as_text=True))
        if isinstance(resp, tuple):
            return _is_future_jwt(resp)
    except Exception:
        pass
    return False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Wrap config reads.  A retry is attempted only for PGRST303; after that,
    # last-known-good data from this worker may be used for up to 15 minutes.
    original_get = app_module.cloud_get_json

    @functools.wraps(original_get)
    def resilient_get(key, local_file, default_data):
        last_exc = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                value = original_get(key, local_file, default_data)
                _remember_json(key, value)
                return value
            except Exception as exc:
                last_exc = exc
                if not _is_future_jwt(exc):
                    raise
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    print(f'[SUPABASE] PGRST303 on {key}; retrying in {delay:.1f}s', flush=True)
                    time.sleep(delay)
        stale = _stale_json(key)
        if stale is not None:
            print(f'[SUPABASE] PGRST303 persists on {key}; serving last-good data', flush=True)
            return stale
        raise last_exc

    app_module.cloud_get_json = resilient_get

    # Upserts are idempotent, so retrying the exact PGRST303 auth rejection is safe.
    original_save = app_module.cloud_save_json

    @functools.wraps(original_save)
    def resilient_save(key, local_file, data):
        last_exc = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                result = original_save(key, local_file, data)
                _remember_json(key, data)
                return result
            except Exception as exc:
                last_exc = exc
                if not _is_future_jwt(exc):
                    raise
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    print(f'[SUPABASE] PGRST303 while saving {key}; retrying in {delay:.1f}s', flush=True)
                    time.sleep(delay)
        raise last_exc

    app_module.cloud_save_json = resilient_save

    app = app_module.app

    # These routes access the orders table directly rather than through
    # cloud_get_json.  Retry only the known PGRST303 response.  The admin list
    # can fall back to a recent successful response so refreshes stay usable.
    for endpoint in ('admin_get_orders', 'create_order'):
        original_view = app.view_functions.get(endpoint)
        if not original_view:
            continue

        def make_wrapper(fn, ep):
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                resp = fn(*args, **kwargs)
                if not _response_has_future_jwt(resp):
                    if ep == 'admin_get_orders':
                        _remember_response(ep, resp)
                    return resp

                for delay in _RETRY_DELAYS:
                    print(f'[SUPABASE] PGRST303 on {ep}; retrying in {delay:.1f}s', flush=True)
                    time.sleep(delay)
                    resp = fn(*args, **kwargs)
                    if not _response_has_future_jwt(resp):
                        if ep == 'admin_get_orders':
                            _remember_response(ep, resp)
                        return resp

                if ep == 'admin_get_orders':
                    stale = _stale_response(ep)
                    if stale is not None:
                        print('[SUPABASE] order list using last-good response during PGRST303', flush=True)
                        return stale
                return resp
            return wrapped

        app.view_functions[endpoint] = make_wrapper(original_view, endpoint)

    @app.after_request
    def _mark_health(resp):
        if resp.status_code == 200 and resp.mimetype == 'application/json' and getattr(__import__('flask').request, 'path', '') == '/api/health':
            try:
                data = resp.get_json(silent=True) or {}
                data['supabase_resilience'] = True
                import json
                resp.set_data(json.dumps(data, ensure_ascii=False))
                resp.headers['Content-Type'] = 'application/json; charset=utf-8'
            except Exception:
                pass
        return resp

    print('[SUPABASE] PGRST303 retry + last-good read fallback enabled', flush=True)
