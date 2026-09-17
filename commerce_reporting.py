"""Phase 2 projections over the existing commerce snapshots and ledger.

All money aggregation uses Decimal. Unknown costs remain null, never zero.
"""
from datetime import date, datetime, time as day_time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from commerce_store import CommerceError

TAIPEI = ZoneInfo('Asia/Taipei')
EXPENSE_CATEGORIES = ('房租', '廣告', '水電', '耗材', '運費', '平台費', '其他')
STOCK_LABELS = {'out': '缺貨', 'low': '低於警戒值', 'threshold': '剛好警戒值', 'normal': '正常', 'untracked': '未追蹤'}


def amount(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def positive_money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result > 10_000_000 or result != result.quantize(Decimal('.01')):
            raise ValueError()
        return float(result)
    except (ValueError, InvalidOperation, TypeError):
        raise CommerceError('BAD_AMOUNT', '金額須大於 0，最多兩位小數', 400)


def iso_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise CommerceError('BAD_DATE', '日期格式須為 YYYY-MM-DD', 400)


def date_range(period='today', start=None, end=None, now=None):
    today = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
    if period == 'today':
        first, last = today, today
    elif period == 'week':
        first = today - timedelta(days=today.weekday())
        last = first + timedelta(days=6)
    elif period == 'month':
        first = today.replace(day=1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif period == 'year':
        first, last = today.replace(month=1, day=1), today.replace(month=12, day=31)
    elif period == 'custom':
        first, last = iso_date(start), iso_date(end)
    else:
        raise CommerceError('BAD_PERIOD', '不支援的報表區間', 400)
    if first > last or (last - first).days > 36600 or last.year >= 9999:
        raise CommerceError('BAD_RANGE', '開始日期不可晚於結束日期，區間最多 100 年', 400)
    return dict(period=period, timezone='Asia/Taipei', start=first.isoformat(), end=last.isoformat(),
                start_unix=int(datetime.combine(first, day_time.min, TAIPEI).timestamp()),
                end_unix=int(datetime.combine(last + timedelta(days=1), day_time.min, TAIPEI).timestamp()))


def stock_status(sku):
    if not sku.get('track_stock'):
        return 'untracked'
    qty, warning = sku['stock_qty'], sku['low_stock_threshold']
    return 'out' if qty == 0 else 'low' if qty < warning else 'threshold' if qty == warning else 'normal'


def replenishment(data, shop):
    models = {str(x['id']): x for x in shop.get('models', [])}
    styles = {str(x['id']): x for x in shop.get('styles', [])}
    groups = {}
    counts = dict.fromkeys(STOCK_LABELS, 0)
    for sku in data['skus']:
        model, style = models.get(sku['model_id']), styles.get(sku['style_id'])
        if not sku['active'] or not model or not style or not model.get('status', True) or not style.get('status', True):
            continue
        status = stock_status(sku)
        counts[status] += 1
        if status not in ('out', 'low', 'threshold'):
            continue
        group = groups.setdefault(sku['style_id'], dict(series_id=sku['style_id'], series_name=style['name'], items=[]))
        target = sku.get('target_stock')
        group['items'].append(dict(sku_id=sku['id'], model_id=sku['model_id'], model_name=model['name'],
            color=sku['color'], stock_qty=sku['stock_qty'], low_stock_threshold=sku['low_stock_threshold'],
            target_stock=target, suggested_quantity=max(0, target - sku['stock_qty']) if target is not None else None,
            status=status, status_label=STOCK_LABELS[status]))
    ordered = sorted(groups.values(), key=lambda x: x['series_name'])
    lines = ['補貨清單（建議數量，尚未入庫）']
    for group in ordered:
        group['items'].sort(key=lambda x: (x['model_name'], x['color']))
        lines.append('\n' + group['series_name'])
        for row in group['items']:
            qty = row['suggested_quantity']
            lines.append(f"{row['model_name']} / {row['color'] or '無色別'}：現有 {row['stock_qty']}，目標 {row['target_stock'] if row['target_stock'] is not None else '未設定'}，建議 {'未設定目標' if qty is None else str(qty) + ' 件'}")
    return dict(schema_version=1, generated_at=datetime.now(TAIPEI).isoformat(), timezone='Asia/Taipei',
                revision=data['revision'], groups=ordered, counts=counts, text='\n'.join(lines),
                total_suggested=sum(r['suggested_quantity'] or 0 for g in ordered for r in g['items']),
                missing_targets=sum(r['target_stock'] is None for g in ordered for r in g['items']))


def report(data, orders, interval):
    # Finance contains immutable amounts plus current lifecycle status. Legacy
    # orders absent from finance use their own recorded total, never today's SKU.
    finances = data['order_finance']
    rows = {oid: dict(row) for oid, row in finances.items()}
    for order in orders:
        oid = order['id']
        if oid in rows and not rows[oid].get('series_name') and order.get('style_name'):
            rows[oid]['series_name'] = order['style_name']
        if oid not in rows:
            rows[oid] = dict(order_id=oid, style_id=order.get('style_id') or 'legacy-unassigned',
                series_name=order.get('style_name') or order.get('style') or '舊單／系列未知',
                revenue=order.get('total', 0), quantity=order.get('quantity', 1),
                status=order.get('status'), created_at_unix=order.get('created_at_unix') or order.get('time', 0),
                cost_known=False, cost_total=None)

    def empty():
        return dict(revenue=Decimal(0), orders=0, units=0, known_cost=Decimal(0), unknown_cost_orders=0)

    total, groups, unknown = empty(), {}, []
    for oid, row in rows.items():
        if row.get('status') == '作廢' or not interval['start_unix'] <= int(row.get('created_at_unix') or 0) < interval['end_unix']:
            continue
        sid = row.get('series_id') or row.get('style_id') or 'legacy-unassigned'
        name = row.get('series_name') or f'舊單系列 {sid}'
        group = groups.setdefault(sid, dict(series_id=sid, names=set(), **empty()))
        group['names'].add(name)
        known = bool(row.get('cost_known') and row.get('cost_total') is not None)
        for item in (total, group):
            item['revenue'] += amount(row.get('revenue'))
            item['orders'] += 1
            item['units'] += int(row.get('quantity') or 0)
            if known:
                item['known_cost'] += amount(row['cost_total'])
            else:
                item['unknown_cost_orders'] += 1
        if not known:
            unknown.append(dict(order_id=oid, series_id=sid, series_name=name, cost_status='成本未知'))

    expenses = [x for x in data.get('expenses', {}).values() if not x.get('voided') and interval['start'] <= x['date'] <= interval['end']]
    expense_total = sum((amount(x['amount']) for x in expenses), Decimal(0))
    def finish(item, expense=None):
        revenue, cost = item['revenue'], item['known_cost']
        complete = item['unknown_cost_orders'] == 0
        item.update(product_cost=cost if complete else None, gross_profit=revenue-cost if complete else None,
                    gross_margin=float((revenue-cost)/revenue*100) if complete and revenue else None,
                    average_order_value=revenue/item['orders'] if item['orders'] else Decimal(0),
                    cost_complete=complete)
        if expense is not None:
            item.update(expenses=expense, net_profit=revenue-cost-expense if complete else None)
        return {k: float(v.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if isinstance(v, Decimal) else v for k, v in item.items()}
    series = []
    for group in groups.values():
        group['series_name'] = ' / '.join(sorted(group.pop('names')))
        series.append(finish(group))
    categories = {name: float(sum((amount(x['amount']) for x in expenses if x['category'] == name), Decimal(0))) for name in EXPENSE_CATEGORIES}
    return dict(schema_version=1, range=interval, summary=finish(total, expense_total),
                series=sorted(series, key=lambda x: x['series_name']), expenses_by_category=categories,
                unknown_cost_orders=unknown, recognition='以訂單成立日計入，排除目前作廢訂單；支出依登記日期。每週由週一開始。')
