"""Admin order lifecycle actions: void/restore/delete with storage cleanup."""
import os
from flask import request

_INSTALLED = False


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

    @app.route('/api/admin/order_action', methods=['POST'])
    def admin_order_action():
        if not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        data = request.get_json(silent=True) or {}
        order_id = valid_order_id(data.get('order_id'))
        action = str(data.get('action') or '').strip().lower()
        if not order_id:
            return no_cache_json({'status': 'error', 'msg': '訂單編號格式錯誤'}, 400)
        if action not in ('void', 'restore', 'delete'):
            return no_cache_json({'status': 'error', 'msg': '不支援的訂單操作'}, 400)

        try:
            if app_module.USE_SUPABASE:
                rows = (app_module.SUPABASE.table('orders')
                        .select('id,status,print_path,mockup_path')
                        .eq('id', order_id).limit(1).execute().data or [])
                if not rows:
                    return no_cache_json({'status': 'error', 'msg': '找不到這筆訂單'}, 404)
                row = rows[0]
                if action == 'void':
                    app_module.SUPABASE.table('orders').update({'status': '作廢'}).eq('id', order_id).execute()
                    return no_cache_json({'status': 'success', 'msg': '訂單已作廢', 'order_id': order_id, 'new_status': '作廢'})
                if action == 'restore':
                    app_module.SUPABASE.table('orders').update({'status': '待處理'}).eq('id', order_id).execute()
                    return no_cache_json({'status': 'success', 'msg': '訂單已恢復', 'order_id': order_id, 'new_status': '待處理'})

                # Delete database row first; storage cleanup is best-effort after the row is gone.
                app_module.SUPABASE.table('orders').delete().eq('id', order_id).execute()
                for path in (row.get('print_path'), row.get('mockup_path')):
                    if path:
                        try:
                            app_module.delete_private_path(path)
                        except Exception as exc:
                            print('[ORDER DELETE] storage cleanup warning:', order_id, repr(exc), flush=True)
                return no_cache_json({'status': 'success', 'msg': '訂單已永久刪除', 'order_id': order_id})

            info_path = os.path.join(app_module.SAVE_DIR, f'{order_id}_info.json')
            if not os.path.exists(info_path):
                return no_cache_json({'status': 'error', 'msg': '找不到這筆訂單'}, 404)
            info = app_module.local_load_json(info_path, {})
            if action in ('void', 'restore'):
                info['status'] = '作廢' if action == 'void' else '待處理'
                app_module.local_save_json(info_path, info)
                status = info['status']
                return no_cache_json({'status': 'success', 'msg': '訂單狀態已更新', 'order_id': order_id, 'new_status': status})

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
        except Exception as exc:
            print('[ORDER ACTION] error:', order_id, action, repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'訂單操作失敗：{exc}'}, 500)

    print('[ORDER] admin void/restore/delete actions enabled', flush=True)
