"""Private POS / inventory core for Benfuwan admin.

Public shop_data keeps customer-facing catalog and sale prices. Cost, stock and
profit snapshots live in a separate authenticated/private store so they are
never exposed through /api/shop_data.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from flask import g, request

_INSTALLED = False
_LOCK = threading.RLock()
COMMERCE_FILE = 'commerce_data.json'
DEFAULT_COMMERCE = {
    'version': 1,
    'style_defaults': {},
    'skus': [],
    'order_finance': {},
}


def _clean_list(value):
    out = []
    src = value if isinstance(value, list) else str(value or '').replace('，', ',').split(',')
    for item in src:
        s = str(item or '').strip()
        if s and s not in out:
            out.append(s)
    return out


def _allowed_colors(style, model_id):
    mapping = style.get('model_colors') if isinstance(style, dict) else None
    if isinstance(mapping, dict):
        specific = _clean_list(mapping.get(model_id))
        if specific:
            return specific
    colors = _clean_list(style.get('colors') if isinstance(style, dict) else [])
    return colors or ['']


def _sku_key(model_id, style_id, color):
    return f'{str(model_id)}\x1f{str(style_id)}\x1f{str(color or "").strip()}'


def _sku_id(model_id, style_id, color):
    digest = hashlib.sha1(_sku_key(model_id, style_id, color).encode('utf-8')).hexdigest()[:18]
    return f'sku_{digest}'


def _as_money(value, allow_none=False):
    if value in (None, '') and allow_none:
        return None
    try:
        number = round(float(value), 2)
    except Exception:
        return None if allow_none else 0.0
    if number < 0:
        number = 0.0
    return min(number, 10_000_000.0)


def _as_int(value, default=0):
    try:
        number = int(float(value))
    except Exception:
        number = default
    return max(0, min(number, 10_000_000))


def _normalize_sku(raw):
    if not isinstance(raw, dict):
        return None
    model_id = str(raw.get('model_id') or '').strip()[:120]
    style_id = str(raw.get('style_id') or '').strip()[:120]
    color = str(raw.get('color') or '').strip()[:80]
    if not model_id or not style_id:
        return None
    return {
        'id': _sku_id(model_id, style_id, color),
        'model_id': model_id,
        'style_id': style_id,
        'color': color,
        'cost_price': _as_money(raw.get('cost_price'), allow_none=True),
        'stock_qty': _as_int(raw.get('stock_qty'), 0),
        'low_stock_threshold': _as_int(raw.get('low_stock_threshold'), 2),
        'track_stock': bool(raw.get('track_stock', False)),
        'active': bool(raw.get('active', True)),
    }


def _normalize_default(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'cost_price': _as_money(raw.get('cost_price'), allow_none=True),
        'low_stock_threshold': _as_int(raw.get('low_stock_threshold'), 2),
        'track_stock': bool(raw.get('track_stock', False)),
    }


def _normalize_store(raw):
    raw = raw if isinstance(raw, dict) else {}
    defaults = {}
    for style_id, value in (raw.get('style_defaults') or {}).items():
        sid = str(style_id or '').strip()[:120]
        if sid:
            defaults[sid] = _normalize_default(value)
    seen = set()
    skus = []
    for item in raw.get('skus') or []:
        sku = _normalize_sku(item)
        if not sku:
            continue
        key = _sku_key(sku['model_id'], sku['style_id'], sku['color'])
        if key in seen:
            continue
        seen.add(key)
        skus.append(sku)
    finance = raw.get('order_finance') if isinstance(raw.get('order_finance'), dict) else {}
    return {
        'version': 1,
        'style_defaults': defaults,
        'skus': skus,
        'order_finance': finance,
    }


def _load(app_module):
    raw = app_module.cloud_get_json('commerce_data', COMMERCE_FILE, DEFAULT_COMMERCE)
    return _normalize_store(raw)


def _save(app_module, data):
    app_module.cloud_save_json('commerce_data', COMMERCE_FILE, _normalize_store(data))


def _sync_skus(app_module, data):
    shop = app_module.cloud_get_json('shop_data', app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA)
    models = [m for m in (shop.get('models') or []) if m.get('status', True)]
    styles = [s for s in (shop.get('styles') or []) if s.get('status', True)]
    existing = {_sku_key(s['model_id'], s['style_id'], s.get('color')): s for s in data.get('skus') or []}
    added = 0
    for model in models:
        model_id = str(model.get('id') or '').strip()
        if not model_id:
            continue
        for style in styles:
            style_id = str(style.get('id') or '').strip()
            if not style_id:
                continue
            default = _normalize_default((data.get('style_defaults') or {}).get(style_id))
            for color in _allowed_colors(style, model_id):
                key = _sku_key(model_id, style_id, color)
                if key in existing:
                    continue
                sku = {
                    'id': _sku_id(model_id, style_id, color),
                    'model_id': model_id,
                    'style_id': style_id,
                    'color': color,
                    'cost_price': default.get('cost_price'),
                    'stock_qty': 0,
                    'low_stock_threshold': default.get('low_stock_threshold', 2),
                    'track_stock': default.get('track_stock', False),
                    'active': True,
                }
                data['skus'].append(sku)
                existing[key] = sku
                added += 1
    return added


def _finance_summary(data):
    revenue = 0.0
    known_cost = 0.0
    known_profit = 0.0
    known_orders = 0
    unknown_cost_orders = 0
    active_orders = 0
    today_revenue = 0.0
    today_profit = 0.0
    today_start = int(time.time()) - (int(time.time()) % 86400)
    for row in (data.get('order_finance') or {}).values():
        if not isinstance(row, dict) or row.get('status') == '作廢':
            continue
        active_orders += 1
        rev = float(row.get('revenue') or 0)
        revenue += rev
        created = int(row.get('created_at_unix') or 0)
        if created >= today_start:
            today_revenue += rev
        if row.get('cost_known'):
            cost = float(row.get('cost_total') or 0)
            profit = float(row.get('gross_profit') or 0)
            known_cost += cost
            known_profit += profit
            known_orders += 1
            if created >= today_start:
                today_profit += profit
        else:
            unknown_cost_orders += 1
    return {
        'orders': active_orders,
        'revenue': round(revenue, 2),
        'known_cost': round(known_cost, 2),
        'gross_profit': round(known_profit, 2),
        'orders_with_cost': known_orders,
        'orders_missing_cost': unknown_cost_orders,
        'today_revenue': round(today_revenue, 2),
        'today_gross_profit': round(today_profit, 2),
    }


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    session = app_module.session
    no_cache_json = app_module.no_cache_json

    @app.route('/api/admin/commerce_data', methods=['GET'])
    def admin_commerce_data():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        try:
            with _LOCK:
                data = _load(app_module)
            return no_cache_json({
                'status': 'success',
                'data': {
                    'version': data['version'],
                    'style_defaults': data['style_defaults'],
                    'skus': data['skus'],
                },
                'summary': _finance_summary(data),
            })
        except Exception as exc:
            print('[COMMERCE] read error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'POS 資料讀取失敗：{exc}'}, 500)

    @app.route('/api/admin/commerce_sync_skus', methods=['POST'])
    def admin_commerce_sync_skus():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        try:
            with _LOCK:
                data = _load(app_module)
                added = _sync_skus(app_module, data)
                _save(app_module, data)
            return no_cache_json({'status': 'success', 'added': added, 'total': len(data['skus']), 'msg': f'已同步商品 SKU，新增 {added} 筆'})
        except Exception as exc:
            print('[COMMERCE] sync error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'SKU 同步失敗：{exc}'}, 500)

    @app.route('/api/admin/save_commerce_data', methods=['POST'])
    def admin_save_commerce_data():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return no_cache_json({'status': 'error', 'msg': '資料格式錯誤'}, 400)
        incoming_skus = payload.get('skus')
        if not isinstance(incoming_skus, list) or len(incoming_skus) > 5000:
            return no_cache_json({'status': 'error', 'msg': 'SKU 資料格式錯誤或數量過多'}, 400)
        incoming_defaults = payload.get('style_defaults') or {}
        if not isinstance(incoming_defaults, dict) or len(incoming_defaults) > 500:
            return no_cache_json({'status': 'error', 'msg': '材質預設資料格式錯誤'}, 400)
        try:
            with _LOCK:
                current = _load(app_module)
                candidate = {
                    'version': 1,
                    'style_defaults': incoming_defaults,
                    'skus': incoming_skus,
                    'order_finance': current.get('order_finance') or {},
                }
                clean = _normalize_store(candidate)
                _save(app_module, clean)
            return no_cache_json({'status': 'success', 'msg': '成本與庫存已儲存', 'count': len(clean['skus'])})
        except Exception as exc:
            print('[COMMERCE] save error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'成本與庫存儲存失敗：{exc}'}, 500)

    @app.route('/api/admin/commerce_set_style_price', methods=['POST'])
    def admin_commerce_set_style_price():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        payload = request.get_json(silent=True) or {}
        style_id = str(payload.get('style_id') or '').strip()[:120]
        price = _as_money(payload.get('price'))
        if not style_id or price <= 0:
            return no_cache_json({'status': 'error', 'msg': '材質或售價格式錯誤'}, 400)
        try:
            with _LOCK:
                shop = app_module.cloud_get_json('shop_data', app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA)
                style = next((s for s in (shop.get('styles') or []) if str(s.get('id')) == style_id), None)
                if not style:
                    return no_cache_json({'status': 'error', 'msg': '找不到這個手機殼材質'}, 404)
                style['price'] = int(round(price))
                app_module.cloud_save_json('shop_data', app_module.DATA_FILE, shop)
            return no_cache_json({'status': 'success', 'style_id': style_id, 'price': style['price'], 'msg': '售價已更新，前台會同步使用新售價'})
        except Exception as exc:
            print('[COMMERCE] price error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'售價更新失敗：{exc}'}, 500)

    # Snapshot sale/cost/profit when an order succeeds. The original orders table
    # schema stays unchanged; finance is stored privately in commerce_data.
    original_create_order = app.view_functions.get('create_order')
    if original_create_order:
        def _commerce_create_order(*args, **kwargs):
            req = request.get_json(silent=True) or {}
            model_id = str(req.get('model_id') or '').strip()
            style_id = str(req.get('style_id') or '').strip()
            color = str(getattr(g, '_bf_order_color', '') or req.get('color_name') or '').strip()
            qty = max(1, min(99, _as_int(req.get('quantity'), 1)))
            with _LOCK:
                data = None
                sku = None
                try:
                    data = _load(app_module)
                    sku = next((s for s in data['skus'] if s.get('active', True) and _sku_key(s.get('model_id'), s.get('style_id'), s.get('color')) == _sku_key(model_id, style_id, color)), None)
                    if sku and sku.get('track_stock') and int(sku.get('stock_qty') or 0) < qty:
                        return no_cache_json({
                            'status': 'error',
                            'code': 'OUT_OF_STOCK',
                            'msg': f'這個規格庫存不足，目前剩 {int(sku.get("stock_qty") or 0)} 個，請洽店員',
                        }, 409)
                except Exception as exc:
                    print('[COMMERCE] pre-order inventory check warning:', repr(exc), flush=True)

                response = app.make_response(original_create_order(*args, **kwargs))
                if not (200 <= response.status_code < 300):
                    return response
                try:
                    body = response.get_json(silent=True) or {}
                    order_id = str(body.get('order_id') or '').strip()
                    total = float(body.get('total') or 0)
                    if not order_id:
                        return response
                    if data is None:
                        data = _load(app_module)
                    if sku is None:
                        sku = next((s for s in data['skus'] if s.get('active', True) and _sku_key(s.get('model_id'), s.get('style_id'), s.get('color')) == _sku_key(model_id, style_id, color)), None)
                    cost_price = sku.get('cost_price') if sku else None
                    cost_known = cost_price is not None
                    cost_total = round(float(cost_price or 0) * qty, 2) if cost_known else None
                    gross_profit = round(total - cost_total, 2) if cost_known else None
                    timestamp = int(time.time())
                    data.setdefault('order_finance', {})[order_id] = {
                        'order_id': order_id,
                        'sku_id': sku.get('id') if sku else '',
                        'model_id': model_id,
                        'style_id': style_id,
                        'color': color,
                        'quantity': qty,
                        'unit_price': round(total / qty, 2) if qty else total,
                        'unit_cost': cost_price if cost_known else None,
                        'revenue': round(total, 2),
                        'cost_total': cost_total,
                        'gross_profit': gross_profit,
                        'cost_known': bool(cost_known),
                        'status': '待處理',
                        'payment_method': str(req.get('payment_method') or ''),
                        'created_at_unix': timestamp,
                        'stock_deducted': False,
                    }
                    if sku and sku.get('track_stock'):
                        sku['stock_qty'] = max(0, int(sku.get('stock_qty') or 0) - qty)
                        data['order_finance'][order_id]['stock_deducted'] = True
                    _save(app_module, data)
                except Exception as exc:
                    print('[COMMERCE] order finance snapshot warning:', repr(exc), flush=True)
                return response
        _commerce_create_order.__name__ = original_create_order.__name__
        app.view_functions['create_order'] = _commerce_create_order

    original_order_action = app.view_functions.get('admin_order_action')
    if original_order_action:
        def _commerce_order_action(*args, **kwargs):
            req = request.get_json(silent=True) or {}
            order_id = str(req.get('order_id') or '').strip()
            action = str(req.get('action') or '').strip().lower()
            requested = str(req.get('new_status') or '').strip()
            with _LOCK:
                data = None
                finance = None
                sku = None
                try:
                    data = _load(app_module)
                    finance = (data.get('order_finance') or {}).get(order_id)
                    if isinstance(finance, dict):
                        sku_id = str(finance.get('sku_id') or '')
                        sku = next((s for s in data['skus'] if str(s.get('id')) == sku_id), None)
                        target = '作廢' if action == 'void' else ('待處理' if action == 'restore' else requested)
                        if finance.get('status') == '作廢' and target != '作廢' and finance.get('stock_deducted') and sku and sku.get('track_stock'):
                            qty = int(finance.get('quantity') or 0)
                            if int(sku.get('stock_qty') or 0) < qty:
                                return no_cache_json({'status': 'error', 'code': 'OUT_OF_STOCK', 'msg': '庫存不足，無法恢復這筆作廢訂單'}, 409)
                except Exception as exc:
                    print('[COMMERCE] order-action precheck warning:', repr(exc), flush=True)

                response = app.make_response(original_order_action(*args, **kwargs))
                if not (200 <= response.status_code < 300) or action == 'delete':
                    return response
                try:
                    body = response.get_json(silent=True) or {}
                    new_status = str(body.get('new_status') or '')
                    if data is None:
                        data = _load(app_module)
                    finance = (data.get('order_finance') or {}).get(order_id)
                    if isinstance(finance, dict):
                        old_status = str(finance.get('status') or '')
                        if finance.get('stock_deducted') and sku and sku.get('track_stock'):
                            qty = int(finance.get('quantity') or 0)
                            if new_status == '作廢' and old_status != '作廢':
                                sku['stock_qty'] = int(sku.get('stock_qty') or 0) + qty
                            elif old_status == '作廢' and new_status != '作廢':
                                sku['stock_qty'] = max(0, int(sku.get('stock_qty') or 0) - qty)
                        finance['status'] = new_status or finance.get('status')
                        _save(app_module, data)
                except Exception as exc:
                    print('[COMMERCE] order-action finance warning:', repr(exc), flush=True)
                return response
        _commerce_order_action.__name__ = original_order_action.__name__
        app.view_functions['admin_order_action'] = _commerce_order_action

    @app.after_request
    def _inject_commerce_admin(resp):
        if request.path == '/admin' and resp.status_code == 200 and resp.mimetype == 'text/html':
            try:
                if getattr(resp, 'direct_passthrough', False):
                    resp.direct_passthrough = False
                html = resp.get_data(as_text=True)
                src = '/static/admin-commerce-v1.js?v=20260917a'
                if src not in html and '</body>' in html:
                    html = html.replace('</body>', f'<script src="{src}"></script></body>')
                resp.set_data(html)
                resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                resp.headers.pop('Content-Length', None)
            except Exception as exc:
                print('[COMMERCE] admin injection warning:', repr(exc), flush=True)
        return resp

    print('[COMMERCE] private POS / cost / inventory / profit core enabled', flush=True)
