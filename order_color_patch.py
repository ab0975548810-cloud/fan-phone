"""Persist model-specific case color without changing the orders table schema.

The selected color is validated against shop_data before order creation. After a
successful order insert, the existing style_name column is updated to include
"・顏色", so the current admin list and printer workflow can see it immediately.
"""
from __future__ import annotations

import json
import os
import time
from flask import g, jsonify, request

_INSTALLED = False
_RETRY_DELAYS = (0.8, 1.6)


def _clean(v):
    out=[]
    src=v if isinstance(v,list) else str(v or '').replace('，',',').split(',')
    for item in src:
        s=str(item or '').strip()
        if s and s not in out:
            out.append(s)
    return out


def _future_jwt(exc):
    t=str(exc or '').lower()
    return 'pgrst303' in t and 'jwt issued at future' in t


def _allowed_colors(style, model_id):
    mapping=style.get('model_colors') if isinstance(style,dict) else None
    if isinstance(mapping,dict):
        override=_clean(mapping.get(model_id))
        if override:
            return override
    return _clean(style.get('colors') if isinstance(style,dict) else [])


def _update_cloud_style_name(app_module, order_id, style_name):
    last=None
    for attempt in range(len(_RETRY_DELAYS)+1):
        try:
            app_module.SUPABASE.table('orders').update({'style_name':style_name}).eq('id',order_id).execute()
            return True
        except Exception as exc:
            last=exc
            if not _future_jwt(exc) or attempt>=len(_RETRY_DELAYS):
                break
            time.sleep(_RETRY_DELAYS[attempt])
    print('[ORDER COLOR] style_name update warning:', repr(last), flush=True)
    return False


def _update_local_style_name(app_module, order_id, style_name):
    try:
        path=os.path.join(app_module.SAVE_DIR,f'{order_id}_info.json')
        if not os.path.exists(path):
            return False
        data=app_module.local_load_json(path,{})
        data['style']=style_name
        app_module.local_save_json(path,data)
        return True
    except Exception as exc:
        print('[ORDER COLOR] local update warning:', repr(exc), flush=True)
        return False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED=True
    app=app_module.app

    @app.before_request
    def _validate_order_color():
        if request.path!='/api/create_order' or request.method!='POST':
            return None
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return None
        model_id=str(data.get('model_id') or '')
        style_id=str(data.get('style_id') or '')
        requested=str(data.get('color_name') or '').strip()
        if len(requested)>40:
            return jsonify({'status':'error','code':'BAD_COLOR','msg':'手機殼顏色格式錯誤'}),400
        try:
            shop=app_module.cloud_get_json('shop_data',app_module.DATA_FILE,app_module.DEFAULT_SHOP_DATA)
            style=next((s for s in shop.get('styles',[]) if str(s.get('id'))==style_id and s.get('status',True)),None)
            if not style:
                return None
            allowed=_allowed_colors(style,model_id)
            color=requested
            if allowed:
                if not color:
                    if len(allowed)==1:
                        color=allowed[0]
                    else:
                        return jsonify({'status':'error','code':'COLOR_REQUIRED','msg':'請重新選擇手機殼顏色後再下單'}),400
                if color not in allowed:
                    return jsonify({'status':'error','code':'COLOR_NOT_AVAILABLE','msg':'這個手機型號目前沒有此顏色，請重新選擇'}),400
            else:
                color=''
            g._bf_order_color=color
            g._bf_order_style_base=str(style.get('name') or '')
        except Exception as exc:
            # Let the original create_order route handle transient DB failures.
            print('[ORDER COLOR] validation fallback:', repr(exc), flush=True)
        return None

    @app.after_request
    def _persist_order_color(resp):
        if request.path!='/api/create_order' or request.method!='POST' or not (200<=resp.status_code<300):
            return resp
        color=str(getattr(g,'_bf_order_color','') or '').strip()
        base=str(getattr(g,'_bf_order_style_base','') or '').strip()
        if not color or not base:
            return resp
        try:
            payload=resp.get_json(silent=True) or {}
            order_id=str(payload.get('order_id') or '').strip()
            if not order_id:
                return resp
            display=f'{base}・{color}'
            if getattr(app_module,'USE_SUPABASE',False):
                _update_cloud_style_name(app_module,order_id,display)
            else:
                _update_local_style_name(app_module,order_id,display)
        except Exception as exc:
            print('[ORDER COLOR] persist warning:', repr(exc), flush=True)
        return resp

    @app.after_request
    def _health_flag(resp):
        if request.path=='/api/health' and resp.status_code==200 and resp.mimetype=='application/json':
            try:
                data=resp.get_json(silent=True) or {}
                data['model_specific_colors']=True
                resp.set_data(json.dumps(data,ensure_ascii=False))
                resp.headers['Content-Type']='application/json; charset=utf-8'
            except Exception:
                pass
        return resp

    print('[ORDER COLOR] model-specific color validation + persistence enabled', flush=True)
