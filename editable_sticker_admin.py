"""Admin-owned editable sticker records inside the existing CAS assets JSON."""
import uuid
from editable_stickers import normalized_area, text_style, public_image, image_bytes


def install(module):
    @module.app.route('/api/admin/editable_sticker',methods=['POST'])
    def editable_sticker_save():
        if not module.session.get('logged_in'):return module.no_cache_json({'status':'error','msg':'未登入'},401)
        try:
            data=module.request.get_json(silent=True) or {}
            assets,_=module.cloud_get_json_versioned('assets',module.ASSETS_FILE,module.DEFAULT_ASSETS)
            items=assets.setdefault('editable_stickers',[])
            asset_id=str(data.get('id') or uuid.uuid4())
            if data.get('action')=='delete':
                assets['editable_stickers']=[r for r in items if r['id']!=asset_id]
            else:
                name=str(data.get('name') or '').strip()
                if not name or len(name)>60:raise ValueError('請填名稱，最多 60 字')
                image_src=str(data.get('imageSrc') or '')
                width,height=image_bytes(public_image(module,image_src),transparent=True)
                item={'id':asset_id,'name':name,'imageSrc':image_src,'textArea':normalized_area(data.get('textArea')), 'defaultTextStyle':text_style(data.get('defaultTextStyle')),'intrinsicSize':{'width':width,'height':height}}
                old=next((i for i,r in enumerate(items) if r['id']==asset_id),None)
                if old is None:items.append(item)
                else:items[old]=item
            version=module.cloud_compare_and_swap_json('assets',module.ASSETS_FILE,assets,data.get('expected_version'))
            return module.no_cache_json({'status':'success','version':version,'data':assets})
        except module.StaleDataError as exc:return module.no_cache_json({'status':'error','code':exc.code,'msg':str(exc)},exc.status)
        except (ValueError,OSError) as exc:return module.no_cache_json({'status':'error','msg':str(exc)},400)
