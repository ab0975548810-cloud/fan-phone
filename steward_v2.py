"""Read-only operational projection for the admin steward panel."""
from flask import session

from commerce_reporting import date_range, report

_INSTALLED = False


def print_projection(rows):
    counts = dict(attention=0, prepared=0, queued=0, printing=0,
                  exception=0, completed=0, unknown=0, failed=0, manual=0)
    issues = []
    for row in rows:
        bucket = row['triage']  # Produced by print_center.triage_bucket, also used by Print Center.
        counts[bucket] += 1
        counts['manual'] += bucket in ('attention', 'exception')
        state = (row.get('job') or {}).get('state') or ''
        order_id = row['order_id']
        issue = None
        kind = 'print'
        if state == 'UNKNOWN':
            counts['unknown'] += 1
            issue = (1, '列印結果不明，請先查核')
        elif state == 'FAILED':
            counts['failed'] += 1
            issue = (2, '銳印回報失敗')
        elif state in ('SENDING', 'CANCELING', 'STARTING'):
            issue = (2, '列印任務待查核')
        elif bucket == 'attention':
            if row.get('binding_required'):
                issue = (3, '舊訂單需要補綁 SKU')
            elif not row.get('profile_available'):
                issue = (3, '缺 production profile')
            elif not row.get('has_print'):
                issue = (5, '缺高清生產圖')
                kind = 'order'
            elif not state:
                issue = (5, '訂單尚未準備列印任務')
        if issue:
            issues.append(dict(priority=issue[0], kind=kind, order_id=order_id,
                               text=f'{issue[1]}・訂單 {order_id}', time=row.get('time') or 0))
    issues.sort(key=lambda item: (item['priority'], -int(item['time']), item['order_id']))
    return counts, issues[:10]


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app

    @app.get('/api/admin/steward/summary')
    def steward_summary():
        if not session.get('logged_in'):
            return app_module.no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        result = {'status': 'success', 'timezone': 'Asia/Taipei',
                  'orders': {'available': False}, 'print': {'available': False}, 'issues': []}
        try:
            interval = date_range('today')
            commerce = app_module.commerce
            for _ in range(4):
                data = commerce.read()
                today_orders = commerce.store.orders_between(interval['start_unix'], interval['end_unix'])
                if commerce.read()['revision'] == data['revision']:
                    break
            else:
                raise RuntimeError('Commerce revision changed during summary')
            active = [row for row in today_orders if row.get('status') != '作廢']
            statuses = [row.get('status') or '待處理' for row in active]
            revenue = report(data, today_orders, interval)['summary']['revenue']
            result['orders'] = dict(available=True, total=len(active), revenue=revenue,
                pending=statuses.count('待處理'), making=statuses.count('製作中'),
                print_flow=statuses.count('待列印') + statuses.count('列印中'),
                completed=statuses.count('已完成'))
        except Exception:
            app.logger.exception('Steward order summary unavailable')
        try:
            counts, issues = print_projection(app_module.print_center.operational_summary_rows())
            result['print'] = {'available': True, **counts}
            result['issues'] = issues
        except Exception:
            app.logger.exception('Steward print summary unavailable')
        return app_module.no_cache_json(result)
