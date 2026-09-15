"""Fast multipart order creation.

Avoids sending multi-megabyte PNGs as base64 JSON and intentionally does not
persist Fabric's image-heavy design JSON. Production/preview PNGs remain the
source of truth for order fulfillment.
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from flask import request

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    no_cache_json = app_module.no_cache_json

    def _read_png(name, max_bytes):
        fs = request.files.get(name)
        if not fs or not fs.filename:
            raise ValueError(f'缺少 {name} 圖片')
        raw = fs.read()
        if not raw:
            raise ValueError(f'{name} 圖片是空的')
        if len(raw) > max_bytes:
            raise ValueError(f'{name} 圖片過大')
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'{name} 必須是 PNG')
        return raw

    @app.route('/api/create_order_fast', methods=['POST'])
    def create_order_fast():
        print_path = None
        mockup_path = None
        try:
            model_id = str(request.form.get('model_id') or '')
            style_id = str(request.form.get('style_id') or '')
            if not model_id or not style_id:
                raise ValueError('缺少手機型號或手機殼款式')

            shop = app_module.cloud_get_json(
                'shop_data', app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA
            )
            model = next((m for m in shop.get('models', [])
                          if str(m.get('id')) == model_id and m.get('status', True)), None)
            style = next((s for s in shop.get('styles', [])
                          if str(s.get('id')) == style_id and s.get('status', True)), None)
            if not model or not style:
                raise ValueError('手機型號或手機殼款式不存在/已停用')

            unit_price = int(style.get('price') or 390)
            if unit_price <= 0:
                raise ValueError('商品售價設定錯誤')
            quantity = max(1, min(99, int(request.form.get('quantity') or 1)))
            total = unit_price * quantity
            customer_name = str(request.form.get('customer_name') or '').strip()
            if not customer_name:
                raise ValueError('請填寫貴姓')
            payment_method = str(request.form.get('payment_method') or '現金')
            if payment_method not in ('現金', 'LINE Pay'):
                raise ValueError('付款方式錯誤')

            print_raw = _read_png('print_file', 45 * 1024 * 1024)
            mockup_raw = _read_png('mockup_file', 16 * 1024 * 1024)

            order_id = f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
            timestamp = int(time.time())
            print_store_path = f'orders/{order_id}/print.png'
            mockup_store_path = f'orders/{order_id}/preview.png'

            # Upload the two independent files concurrently. This usually saves
            # several seconds on Tokyo -> Supabase round trips.
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_print = pool.submit(
                    app_module.upload_private_bytes, print_store_path, print_raw, 'image/png'
                )
                f_mock = pool.submit(
                    app_module.upload_private_bytes, mockup_store_path, mockup_raw, 'image/png'
                )
                print_path = f_print.result()
                mockup_path = f_mock.result()

            order_payload = {
                'id': order_id,
                'customer_name': customer_name,
                'payment_method': payment_method,
                'model_id': model_id,
                'model_name': model.get('name') or request.form.get('model_name') or '',
                'style_id': style_id,
                'style_name': style.get('name') or request.form.get('style_name') or '',
                'unit_price': unit_price,
                'quantity': quantity,
                'total': total,
                'status': '待處理',
                # Deliberately omitted: the old Fabric JSON duplicated every
                # embedded image and made checkout uploads unnecessarily huge.
                'design_json': None,
                'print_path': print_path,
                'mockup_path': mockup_path,
                'created_at_unix': timestamp,
            }

            if app_module.USE_SUPABASE:
                try:
                    app_module.SUPABASE.table('orders').insert(order_payload).execute()
                except Exception:
                    app_module.delete_private_path(print_path)
                    app_module.delete_private_path(mockup_path)
                    raise
            else:
                local_info = {
                    'order_id': order_id,
                    'model': order_payload['model_name'],
                    'style': order_payload['style_name'],
                    'price': unit_price,
                    'quantity': quantity,
                    'total': total,
                    'customer_name': customer_name,
                    'customer_phone': '未提供',
                    'address': '現場取件',
                    'payment_method': payment_method,
                    'status': '待處理',
                    'time': timestamp,
                    'design_json': None,
                    'print_url': f'/orders/{print_path}',
                    'mockup_url': f'/orders/{mockup_path}',
                }
                app_module.local_save_json(
                    os.path.join(app_module.SAVE_DIR, f'{order_id}_info.json'), local_info
                )

            return no_cache_json({
                'status': 'success', 'order_id': order_id, 'total': total,
                'msg': '訂單建立成功', 'transport': 'multipart-fast'
            })
        except ValueError as exc:
            return no_cache_json({'status': 'error', 'msg': str(exc)}, 400)
        except Exception as exc:
            if print_path:
                app_module.delete_private_path(print_path)
            if mockup_path:
                app_module.delete_private_path(mockup_path)
            print('[ORDER FAST] create error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': f'訂單建立失敗：{exc}'}, 500)

    print('[ORDER FAST] multipart order endpoint enabled', flush=True)
