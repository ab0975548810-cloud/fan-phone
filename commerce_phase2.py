"""Admin operations on the existing Commerce.mutate transaction boundary."""
import hashlib
import json
import re
import time
from flask import request
from commerce_store import CommerceError
from commerce_reporting import EXPENSE_CATEGORIES, date_range, iso_date, positive_money, replenishment, report


def install(app_module, guarded):
    from commerce_patch import _ledger, _shop
    app, commerce, reply = app_module.app, app_module.commerce, app_module.no_cache_json

    def operation(kind, payload, change):
        key = payload.get('idempotency_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
            raise CommerceError('IDEMPOTENCY_REQUIRED', '缺少操作識別，請重新整理', 400)
        digest = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != 'idempotency_key'},
                    sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        signature = ['phase2', kind, digest]
        def update(data):
            prior = data['actions'].get(key)
            if prior:
                if prior['signature'] != signature:
                    raise CommerceError('IDEMPOTENCY_CONFLICT', '此操作已送出不同內容，請先確認上次結果')
                return prior['response'], None, ''
            result = change(data, key)
            data['actions'][key] = dict(signature=signature, response=result)
            return result, None, ''
        return reply(commerce.mutate(update))

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise CommerceError('BAD_DATA', '資料格式錯誤', 400)
        return data

    @app.get('/api/admin/replenishment')
    @guarded
    def admin_replenishment():
        return reply(dict(status='success', data=replenishment(commerce.read(), _shop(app_module))))

    @app.post('/api/admin/purchase_received')
    @guarded
    def admin_purchase_received():
        req = payload()
        rows = req.get('items')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise CommerceError('BAD_ITEMS', '請選擇 1 至 500 個到貨品項', 400)
        note = str(req.get('note') or '').strip()
        if len(note) > 500:
            raise CommerceError('BAD_NOTE', '備註最多 500 字', 400)
        def update(data, key):
            skus = {s['id']: s for s in data['skus']}
            seen, received = set(), 0
            for row in rows:
                if not isinstance(row, dict):
                    raise CommerceError('BAD_ITEMS', '到貨品項格式錯誤', 400)
                sid, qty = row.get('sku_id'), row.get('quantity')
                if not isinstance(sid, str) or sid not in skus or sid in seen or not skus[sid]['active'] or not skus[sid]['track_stock']:
                    raise CommerceError('BAD_SKU', '品項已停用、未追蹤庫存或重複，請重新選擇', 400)
                if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 10_000_000 or skus[sid]['stock_qty'] + qty > 10_000_000:
                    raise CommerceError('BAD_QUANTITY', '到貨數量須為正整數，總庫存不得超過一千萬', 400)
                seen.add(sid)
                _ledger(data, skus[sid], qty, 'PURCHASE_RECEIVED', f'purchase:{key}:{sid}')
                data['inventory_ledger'][-1].update(note=note, receipt_id=key)
                received += qty
            return dict(status='success', received=received, receipt_id=key, msg=f'已入庫 {received} 件')
        return operation('purchase', req, update)

    @app.get('/api/admin/commerce_report')
    @guarded
    def admin_commerce_report():
        interval = date_range(request.args.get('period', 'today'), request.args.get('start'), request.args.get('end'))
        for _ in range(4):
            data = commerce.read()
            orders = commerce.store.orders_between(interval['start_unix'], interval['end_unix'])
            if commerce.read()['revision'] == data['revision']:
                return reply(dict(status='success', data=report(data, orders, interval)))
        raise CommerceError('REPORT_BUSY', '資料正在更新，請重新載入報表')

    @app.get('/api/admin/expenses')
    @guarded
    def admin_expenses():
        rows = sorted(commerce.read()['expenses'].values(), key=lambda x: (x['date'], x['id']), reverse=True)
        return reply(dict(status='success', data=rows, categories=list(EXPENSE_CATEGORIES)))

    @app.post('/api/admin/expense')
    @guarded
    def admin_expense():
        req = payload()
        action = req.get('action', 'save')
        if action not in ('save', 'void'):
            raise CommerceError('BAD_ACTION', '不支援的支出操作', 400)
        if action == 'save':
            day = iso_date(req.get('date')).isoformat()
            money = positive_money(req.get('amount'))
            category = req.get('category')
            note = str(req.get('note') or '').strip()
            if category not in EXPENSE_CATEGORIES or len(note) > 500:
                raise CommerceError('BAD_EXPENSE', '請選擇支出分類，備註最多 500 字', 400)
        def update(data, key):
            eid = req.get('expense_id') or 'expense_' + hashlib.sha256(key.encode()).hexdigest()[:24]
            if not isinstance(eid, str):
                raise CommerceError('BAD_EXPENSE', '支出識別格式錯誤', 400)
            old = data['expenses'].get(eid)
            if (req.get('expense_id') or action == 'void') and not old:
                raise CommerceError('EXPENSE_NOT_FOUND', '找不到支出紀錄', 404)
            if old and (old['version'] != req.get('expected_version') or old.get('voided')):
                raise CommerceError('STALE_EXPENSE', '支出已被更新或作廢，請重新整理')
            new = dict(old) if action == 'void' else dict(id=eid, date=day, category=category, amount=money, note=note, voided=False)
            new.update(version=(old['version'] if old else 0) + 1, updated_at_unix=int(time.time()))
            if action == 'void':
                new['voided'] = True
            data['expenses'][eid] = new
            data['expense_ledger'].append(dict(id=key, expense_id=eid, action=action, before=old, after=dict(new), source='admin', created_at_unix=int(time.time())))
            return dict(status='success', expense=new, msg='支出已作廢' if action == 'void' else '支出已儲存')
        return operation('expense', req, update)
