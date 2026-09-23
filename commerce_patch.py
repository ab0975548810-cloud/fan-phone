"""Private POS / inventory core for Benfuwan admin.

Public shop_data keeps customer-facing catalog and sale prices. Cost, stock and
profit snapshots live in a separate authenticated/private store so they are
never exposed through /api/shop_data.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from commerce_store import Store, CommerceError
import time
from flask import g, request

_INSTALLED = False
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
        'target_stock': _as_int(raw.get('target_stock')) if raw.get('target_stock') not in (None, '') else None,
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
        'version': 3,
        'expenses': raw.get('expenses', {}),
        'expense_ledger': raw.get('expense_ledger', []),
        'revision': int(raw.get('revision', 0)),
        'inventory_ledger': raw.get('inventory_ledger', []),
        'requests': raw.get('requests', {}),
        'actions': raw.get('actions', {}),
        'style_defaults': defaults,
        'skus': skus,
        'order_finance': finance,
    }


def _shop(app_module):
    if app_module.USE_SUPABASE:
        rows = app_module.SUPABASE.table('app_store').select('value').eq('key', 'shop_data').limit(1).execute().data
        if not rows:
            raise RuntimeError('Missing production catalog')
        return rows[0]['value']
    return app_module.local_load_json(app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA)


def _sync_skus(app_module, data):
    shop = _shop(app_module)
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
                    'target_stock': None,
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
    midnight = datetime.fromtimestamp(time.time(), ZoneInfo('Asia/Taipei')).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = midnight.timestamp()
    tomorrow = (midnight + timedelta(days=1)).timestamp()
    for row in (data.get('order_finance') or {}).values():
        if not isinstance(row, dict) or row.get('status') == '作廢':
            continue
        active_orders += 1
        rev = float(row.get('revenue') or 0)
        revenue += rev
        created = int(row.get('created_at_unix') or 0)
        if today_start <= created < tomorrow:
            today_revenue += rev
        if row.get('cost_known'):
            cost = float(row.get('cost_total') or 0)
            profit = float(row.get('gross_profit') or 0)
            known_cost += cost
            known_profit += profit
            known_orders += 1
            if today_start <= created < tomorrow:
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


def _ledger(data, sku, delta, reason, identity, order_id='', source='admin'):
    balance = int(sku['stock_qty']) + delta
    if balance < 0:
        raise CommerceError('OUT_OF_STOCK', '庫存不足，請重新確認數量')
    if any(x['id'] == identity for x in data['inventory_ledger']):
        raise CommerceError('DUPLICATE_TRANSACTION', '庫存異動識別重複')
    data['inventory_ledger'].append(dict(id=identity, sku_id=sku['id'], delta=delta,
        balance_after=balance, reason=reason, order_id=order_id,
        created_at_unix=int(time.time()), source=source))
    sku['stock_qty'] = balance


class Commerce:
    def __init__(self, app_module):
        self.app = app_module
        self.store = Store(app_module)

    def read(self):
        return _normalize_store(self.store.read())

    def mutate(self, fn):
        for _ in range(12):
            data = self.read()
            result, order, action = fn(data)
            if self.store.commit(data['revision'], data, order, action):
                return result
        raise CommerceError('BUSY', '其他訂單正在更新庫存，請以同一筆操作重試')

    def replay(self, key, fingerprint, data=None):
        prior = (data if data is not None else self.read())['requests'].get(key)
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise CommerceError('IDEMPOTENCY_CONFLICT', '同一送單識別已用於不同內容，請勿重複送出')
            return prior['response']

    def create(self, order):
        key, fingerprint = g.commerce_key, g.commerce_fingerprint
        def update(data):
            prior = self.replay(key, fingerprint, data)
            if prior:
                return prior, None, ''
            color = str(getattr(g, '_bf_order_color', '') or '')
            _sync_skus(self.app, data)
            sku = next((s for s in data['skus'] if _sku_key(s['model_id'], s['style_id'], s['color']) ==
                        _sku_key(order['model_id'], order['style_id'], color)), None)
            if not sku or not sku['active']:
                raise CommerceError('SKU_UNAVAILABLE', '此規格尚未啟用，請洽店員')
            qty, total = order['quantity'], order['total']
            cost = sku['cost_price']
            finance = dict(order_id=order['id'], sku_id=sku['id'], model_id=order['model_id'],
                style_id=order['style_id'], series_id=order['style_id'],
                series_name=str(next((s.get('name') for s in getattr(g, 'commerce_shop', {}).get('styles', []) if str(s['id']) == order['style_id']), order['style_id'])),
                color=color, quantity=qty, unit_price=order['unit_price'],
                unit_cost=cost, revenue=total, cost_known=cost is not None,
                cost_total=round(cost * qty, 2) if cost is not None else None,
                gross_profit=round(total - cost * qty, 2) if cost is not None else None,
                status='待處理', payment_method=order['payment_method'],
                created_at_unix=order['created_at_unix'], stock_deducted=sku['track_stock'],
                inventory_quantity=qty if sku['track_stock'] else 0, inventory_reserved=bool(sku['track_stock']),
                inventory_sequence=0)
            if sku['track_stock']:
                _ledger(data, sku, -qty, 'ORDER_CREATED', order['id'] + ':0', order['id'], 'checkout')
            data['order_finance'][order['id']] = finance
            result = dict(status='success', order_id=order['id'], total=total, msg='訂單建立成功')
            # Phase 3.3 eligibility is committed with the order transaction.
            # Historical request records lack this marker and must never become
            # auto-print eligible merely because their response is replayed.
            data['requests'][key] = dict(
                fingerprint=fingerprint, response=result, auto_print_v1=True)
            return result, order, 'create'
        return self.mutate(update)

    def action(self, order_id, action, target, key=''):
        signature = [order_id, action, target]
        cleanup = self.store.order(order_id) if action == 'delete' else None
        if action == 'delete' and hasattr(self.app, 'print_center'):
            active = self.app.print_center.store.active_job(order_id)
            if active:
                raise CommerceError('ACTIVE_PRINT_JOB', '此訂單仍有進行中的列印任務，完成或取消後才能永久刪除')
        def update(data):
            if key and key in data['actions']:
                prior = data['actions'][key]
                if prior['signature'] != signature:
                    raise CommerceError('IDEMPOTENCY_CONFLICT', '操作識別已用於不同操作')
                return prior['response'], None, ''
            order = self.store.order(order_id)
            if not order:
                raise CommerceError('ORDER_NOT_FOUND', '找不到這筆訂單', 404)
            if order.get('status') == '作廢' and action not in ('restore', 'delete') and target != '作廢':
                raise CommerceError('VOID_ORDER', '作廢訂單不可由背景流程恢復狀態')
            if action == 'delete' and order['status'] != '作廢':
                raise CommerceError('VOID_REQUIRED', '請先作廢回補庫存，再刪除訂單')
            if target in ('待列印', '列印中', '已完成') and not order.get('print_path'):
                raise CommerceError('PRINT_FILE_REQUIRED', '缺少高清生產圖，無法更新狀態')
            finance = data['order_finance'].get(order_id)
            if finance and action != 'delete':
                # Migrate the prior PR snapshot without inventing historical deductions.
                qty = finance.get('inventory_quantity', finance.get('quantity', 0) if finance.get('stock_deducted') else 0)
                reserved = finance.get('inventory_reserved', bool(qty and finance['status'] != '作廢'))
                want_reserved = bool(qty and target != '作廢')
                if reserved != want_reserved:
                    sku = next((s for s in data['skus'] if s['id'] == finance['sku_id']), None)
                    if sku is None:
                        raise CommerceError('SKU_MISSING', '歷史訂單 SKU 遺失，請先修復庫存資料')
                    seq = finance.get('inventory_sequence', 0) + 1
                    _ledger(data, sku, -qty if want_reserved else qty,
                            'ORDER_RESTORED' if want_reserved else 'ORDER_VOID', f'{order_id}:{seq}', order_id)
                    finance['inventory_sequence'] = seq
                finance.update(inventory_quantity=qty, inventory_reserved=want_reserved, status=target)
            result = dict(status='success', order_id=order_id, new_status=target, msg='訂單狀態已更新')
            if action == 'delete':
                # Finance and ledger remain for audit; deletion never erases accounting.
                result['msg'] = '訂單已刪除；庫存異動與財務紀錄保留'
            if key:
                data['actions'][key] = dict(signature=signature, response=result)
            return result, dict(id=order_id, status=target), 'delete' if action == 'delete' else 'status'
        result = self.mutate(update)
        if cleanup:
            for name in ('print_path', 'mockup_path'):
                self.app.delete_private_path(cleanup.get(name))
        return result


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app, session, reply = app_module.app, app_module.session, app_module.no_cache_json
    commerce = Commerce(app_module)
    app_module.commerce = commerce

    @app.errorhandler(CommerceError)
    def commerce_error(exc):
        return reply(dict(status='error', code=exc.code, msg=str(exc)), exc.status)

    def guarded(fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('logged_in'):
                return reply(dict(status='error', msg='未登入'), 401)
            try:
                return fn(*args, **kwargs)
            except CommerceError:
                raise
            except Exception as exc:
                app.logger.exception('Commerce transaction failed')
                return reply(dict(status='error', code='COMMERCE_UNAVAILABLE', msg='商務資料未完成寫入，請重試原操作'), 503)
        return wrapped

    @app.route('/api/admin/commerce_data')
    @guarded
    def admin_commerce_data():
        data = commerce.read()
        return reply(dict(status='success', data={k: data[k] for k in ('version', 'revision', 'skus', 'style_defaults')},
                          summary=_finance_summary(data)))

    @app.route('/api/admin/inventory_ledger')
    @guarded
    def inventory_ledger():
        data = commerce.read()
        return reply(dict(status='success', data=data['inventory_ledger'][-200:]))

    @app.route('/api/admin/commerce_sync_skus', methods=['POST'])
    @guarded
    def admin_commerce_sync_skus():
        def update(data):
            added = _sync_skus(app_module, data)
            return dict(status='success', added=added, total=len(data['skus'])), None, ''
        return reply(commerce.mutate(update))

    @app.route('/api/admin/save_commerce_data', methods=['POST'])
    @guarded
    def admin_save_commerce_data():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('skus'), list) or len(payload['skus']) > 5000:
            raise CommerceError('BAD_DATA', 'SKU 資料格式錯誤', 400)
        if not isinstance(payload.get('style_defaults', {}), dict):
            raise CommerceError('BAD_DATA', '材質預設資料格式錯誤', 400)
        def update(data):
            if payload.get('revision') != data['revision']:
                raise CommerceError('STALE_INVENTORY', '庫存或設定已更新，請重新整理後再修改；本次未儲存')
            existing = {s['id']: s for s in data['skus']}
            seen = set()
            for raw in payload['skus']:
                if not isinstance(raw, dict):
                    raise CommerceError('BAD_SKU', 'SKU 格式錯誤', 400)
                for field in ('stock_qty', 'low_stock_threshold', 'target_stock'):
                    value = raw.get(field)
                    if field == 'target_stock' and value is None:
                        continue
                    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
                        raise CommerceError('BAD_QUANTITY', '庫存設定須為零至一千萬的整數', 400)
                value = raw.get('cost_price')
                if value is not None:
                    from decimal import Decimal, InvalidOperation
                    try:
                        cost = Decimal(str(value))
                        if not cost.is_finite() or cost < 0 or cost > 10_000_000 or cost != cost.quantize(Decimal('.01')):
                            raise ValueError()
                    except (ValueError, InvalidOperation):
                        raise CommerceError('BAD_COST', '成本須為非負金額，最多兩位小數', 400)
                sku = _normalize_sku(raw)
                if not sku or sku['id'] not in existing or sku['id'] in seen:
                    raise CommerceError('BAD_SKU', 'SKU 不存在或重複，請先同步商品', 400)
                seen.add(sku['id'])
                old = existing[sku['id']]
                delta = sku['stock_qty'] - old['stock_qty']
                if delta:
                    _ledger(data, old, delta, 'MANUAL_ADJUST', f"admin:{data['revision']}:{sku['id']}")
                old.update(sku)
            data['style_defaults'] = _normalize_store({'style_defaults': payload.get('style_defaults', {})})['style_defaults']
            return dict(status='success', msg='成本與庫存已儲存'), None, ''
        return reply(commerce.mutate(update))

    @app.route('/api/admin/commerce_set_style_price', methods=['POST'])
    @guarded
    def admin_commerce_set_style_price():
        payload = request.get_json(silent=True) or {}
        price, style_id = _as_money(payload.get('price')), str(payload.get('style_id') or '')
        if price <= 0:
            raise CommerceError('BAD_PRICE', '售價必須大於零', 400)
        shop = _shop(app_module)
        style = next((s for s in shop['styles'] if str(s['id']) == style_id), None)
        if not style:
            raise CommerceError('STYLE_NOT_FOUND', '找不到材質', 404)
        style['price'] = int(round(price))
        try:
            version = app_module.cloud_compare_and_swap_json(
                'shop_data', app_module.DATA_FILE, shop, payload.get('expected_version'))
        except app_module.StaleDataError as exc:
            raise CommerceError(exc.code, str(exc), exc.status)
        return reply(dict(status='success', price=style['price'], version=version))

    from commerce_phase2 import install as install_phase2
    install_phase2(app_module, guarded)

    original = app.view_functions['create_order']
    def create_order():
        req = request.get_json(silent=True)
        if not isinstance(req, dict):
            raise CommerceError('BAD_DATA', '下單格式錯誤', 400)
        key = request.headers.get('Idempotency-Key') or req.get('idempotency_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
            raise CommerceError('IDEMPOTENCY_REQUIRED', '請重新整理頁面後送單（缺少送單識別）', 400)
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in req.items() if k != 'idempotency_key'},
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        g.commerce_key, g.commerce_fingerprint = key, fingerprint
        # Color is saved inside the transaction, not by a post-response write.
        g.commerce_atomic = True
        try:
            prior = commerce.replay(key, fingerprint)
            if prior:
                return reply(prior)
            shop = _shop(app_module)
            style = next((s for s in shop['styles'] if str(s['id']) == str(req.get('style_id'))), None)
            if style:
                allowed = _allowed_colors(style, str(req.get('model_id')))
                color = str(req.get('color_name') or '').strip()
                if not color and len(allowed) == 1:
                    color = allowed[0]
                if color not in allowed:
                    raise CommerceError('COLOR_NOT_AVAILABLE', '請重新選擇手機殼顏色', 400)
                g._bf_order_color = color
            g.commerce_shop = shop
            return original()
        except CommerceError:
            raise
        except Exception:
            app.logger.exception('Checkout persistence unavailable')
            return reply(dict(status='error', code='COMMERCE_UNAVAILABLE', msg='訂單尚未確認，請重試原訂單'), 503)
    app.view_functions['create_order'] = create_order

    @app.after_request
    def inject_commerce(resp):
        if request.path == '/admin' and resp.status_code == 200 and resp.mimetype == 'text/html':
            resp.direct_passthrough = False
            html = resp.get_data(as_text=True)
            src = '/static/admin-commerce-v1.js?v=20260923cas1'
            if src not in html:
                resp.set_data(html.replace('</body>', f'<link rel="stylesheet" href="/static/admin-commerce.css?v=20260918d"><script src="{src}"></script></body>'))
            resp.headers['Cache-Control'] = 'no-store'
        return resp
