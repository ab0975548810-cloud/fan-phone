"""Admin order lifecycle actions with guarded production workflow statuses."""
import os
from commerce_store import CommerceError
from flask import request

_INSTALLED = False
ORDER_STATUSES = ('待處理', '製作中', '待列印', '列印中', '已完成', '作廢')
PRINT_FILE_REQUIRED = {'待列印', '列印中', '已完成'}


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    session = app_module.session
    no_cache_json = app_module.no_cache_json

    def valid_order_id(value):
        value = str(value or '').strip()
        if not value or len(value) > 80:
            return ''
        allowed = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
        return value if all(ch in allowed for ch in value) else ''

    def validate_new_status(value):
        status = str(value or '').strip()
        return status if status in ORDER_STATUSES else ''

    def ensure_print_ready(status, has_print):
        if status in PRINT_FILE_REQUIRED and not has_print:
            return no_cache_json({
                'status': 'error',
                'code': 'PRINT_FILE_REQUIRED',
                'msg': '這筆訂單尚無高清生產圖，不能進入待列印／列印中／已完成狀態',
            }, 409)
        return None

    @app.route('/api/admin/order_action', methods=['POST'])
    def admin_order_action():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)

        data = request.get_json(silent=True) or {}
        order_id = valid_order_id(data.get('order_id'))
        action = str(data.get('action') or '').strip().lower()
        if not order_id:
            return no_cache_json({'status': 'error', 'msg': '訂單編號格式錯誤'}, 400)
        if action not in ('void', 'restore', 'delete', 'set_status'):
            return no_cache_json({'status': 'error', 'msg': '不支援的訂單操作'}, 400)

        requested_status = ''
        if action == 'set_status':
            requested_status = validate_new_status(data.get('new_status'))
            if not requested_status:
                return no_cache_json({
                    'status': 'error',
                    'msg': '訂單狀態不合法',
                    'allowed_statuses': list(ORDER_STATUSES),
                }, 400)

        try:
            if hasattr(app_module, 'commerce'):
                target = '作廢' if action in ('void', 'delete') else ('待處理' if action == 'restore' else requested_status)
                result = app_module.commerce.action(order_id, action, target, str(data.get('idempotency_key') or '')[:100])
                return no_cache_json(result)
            if app_module.USE_SUPABASE:
                rows = (app_module.SUPABASE.table('orders')
                        .select('id,status,print_path,mockup_path')
                        .eq('id', order_id).limit(1).execute().data or [])
                if not rows:
                    return no_cache_json({'status': 'error', 'msg': '找不到這筆訂單'}, 404)
                row = rows[0]

                if action == 'delete':
                    app_module.SUPABASE.table('orders').delete().eq('id', order_id).execute()
                    for path in (row.get('print_path'), row.get('mockup_path')):
                        if path:
                            try:
                                app_module.delete_private_path(path)
                            except Exception as exc:
                                print('[ORDER DELETE] storage cleanup warning:', order_id, repr(exc), flush=True)
                    return no_cache_json({'status': 'success', 'msg': '訂單已永久刪除', 'order_id': order_id})

                new_status = '作廢' if action == 'void' else ('待處理' if action == 'restore' else requested_status)
                blocked = ensure_print_ready(new_status, bool(row.get('print_path')))
                if blocked:
                    return blocked
                app_module.SUPABASE.table('orders').update({'status': new_status}).eq('id', order_id).execute()
                return no_cache_json({
                    'status': 'success',
                    'msg': '訂單狀態已更新',
                    'order_id': order_id,
                    'new_status': new_status,
                })

            info_path = os.path.join(app_module.SAVE_DIR, f'{order_id}_info.json')
            if not os.path.exists(info_path):
                return no_cache_json({'status': 'error', 'msg': '找不到這筆訂單'}, 404)
            info = app_module.local_load_json(info_path, {})

            if action == 'delete':
                try:
                    os.remove(info_path)
                except FileNotFoundError:
                    pass
                for filename in list(os.listdir(app_module.SAVE_DIR)):
                    if order_id in filename:
                        try:
                            os.remove(os.path.join(app_module.SAVE_DIR, filename))
                        except Exception as exc:
                            print('[ORDER DELETE] local cleanup warning:', filename, repr(exc), flush=True)
                return no_cache_json({'status': 'success', 'msg': '訂單已永久刪除', 'order_id': order_id})

            new_status = '作廢' if action == 'void' else ('待處理' if action == 'restore' else requested_status)
            has_print = bool(info.get('print_url'))
            blocked = ensure_print_ready(new_status, has_print)
            if blocked:
                return blocked
            info['status'] = new_status
            app_module.local_save_json(info_path, info)
            return no_cache_json({
                'status': 'success',
                'msg': '訂單狀態已更新',
                'order_id': order_id,
                'new_status': new_status,
            })
        except CommerceError:
            raise
        except Exception as exc:
            print('[ORDER ACTION] error:', order_id, action, repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'訂單操作失敗：{exc}'}, 500)

    print('[ORDER] lifecycle workflow enabled:', ', '.join(ORDER_STATUSES), flush=True)
