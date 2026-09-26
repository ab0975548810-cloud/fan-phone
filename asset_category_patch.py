"""Sticker category management for the admin asset library."""

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    request = app_module.request
    session = app_module.session
    no_cache_json = app_module.no_cache_json
    cloud_get_json_versioned = app_module.cloud_get_json_versioned
    cloud_compare_and_swap_json = app_module.cloud_compare_and_swap_json
    stale_data_error = app_module.StaleDataError
    default_assets = app_module.DEFAULT_ASSETS

    def _assets_file():
        return app_module.ASSETS_FILE

    def _require_admin():
        return bool(session.get('logged_in'))

    def _clean_category(value):
        value = str(value or '').strip()
        if not value:
            raise ValueError('請輸入分類名稱')
        if len(value) > 24:
            raise ValueError('分類名稱請控制在 24 個字以內')
        if value == '全部':
            raise ValueError('「全部」是系統分類，不能修改')
        return value

    @app.route('/api/admin/sticker_category', methods=['POST'])
    def admin_sticker_category():
        if not _require_admin():
            return no_cache_json({'status': 'error'}, 401)
        try:
            body = request.get_json(silent=True) or {}
            action = str(body.get('action') or '').strip()
            expected_version = body.get('expected_version')
            assets_file = _assets_file()
            assets, _ = cloud_get_json_versioned('assets', assets_file, default_assets)
            cats = assets.setdefault('categories', ['全部'])
            if '全部' not in cats:
                cats.insert(0, '全部')

            if action == 'create':
                name = _clean_category(body.get('name'))
                if name not in cats:
                    cats.append(name)
                version = cloud_compare_and_swap_json('assets', assets_file, assets, expected_version)
                return no_cache_json({'status': 'success', 'category': name, 'version': version})

            if action == 'rename':
                old = _clean_category(body.get('old'))
                new = _clean_category(body.get('new'))
                if old not in cats:
                    raise ValueError('找不到原本的分類')
                if new != old and new in cats:
                    assets['categories'] = [c for c in cats if c != old]
                else:
                    assets['categories'] = [new if c == old else c for c in cats]
                moved = 0
                for sticker in assets.get('stickers', []):
                    if sticker.get('category') == old:
                        sticker['category'] = new
                        moved += 1
                version = cloud_compare_and_swap_json('assets', assets_file, assets, expected_version)
                return no_cache_json({'status': 'success', 'category': new, 'moved': moved, 'version': version})

            if action == 'delete':
                name = _clean_category(body.get('name'))
                # Even if a stale client no longer sees the category list entry,
                # still allow cleaning up sticker rows that use this category.
                assets['categories'] = [c for c in cats if c != name]
                moved = 0
                for sticker in assets.get('stickers', []):
                    if sticker.get('category') == name:
                        sticker['category'] = '未分類'
                        moved += 1
                version = cloud_compare_and_swap_json('assets', assets_file, assets, expected_version)
                return no_cache_json({'status': 'success', 'deleted': name, 'moved': moved, 'version': version})

            if action == 'move':
                name = _clean_category(body.get('name'))
                ids = body.get('ids') or []
                if not isinstance(ids, list) or not ids:
                    raise ValueError('請先選擇要移動的貼紙')
                wanted = {str(x) for x in ids if x}
                if name != '未分類' and name not in cats:
                    cats.append(name)
                moved = 0
                for sticker in assets.get('stickers', []):
                    if str(sticker.get('id')) in wanted:
                        sticker['category'] = name
                        moved += 1
                version = cloud_compare_and_swap_json('assets', assets_file, assets, expected_version)
                return no_cache_json({'status': 'success', 'category': name, 'moved': moved, 'version': version})

            if action == 'delete_stickers':
                ids = body.get('ids') or []
                if not isinstance(ids, list) or not ids:
                    raise ValueError('請先選擇要刪除的貼紙')
                wanted = {str(x) for x in ids if x}
                before = len(assets.get('stickers', []))
                assets['stickers'] = [
                    s for s in assets.get('stickers', [])
                    if str(s.get('id')) not in wanted
                ]
                deleted = before - len(assets['stickers'])
                version = cloud_compare_and_swap_json('assets', assets_file, assets, expected_version)
                return no_cache_json({'status': 'success', 'deleted': deleted, 'version': version})

            raise ValueError('不支援的分類操作')
        except stale_data_error as exc:
            return no_cache_json({'status': 'error', 'code': exc.code, 'msg': str(exc)}, exc.status)
        except ValueError as exc:
            return no_cache_json({'status': 'error', 'msg': str(exc)}, 400)
        except Exception as exc:
            return no_cache_json({'status': 'error', 'msg': str(exc)}, 500)

    print('[ASSETS] sticker category management enabled', flush=True)
