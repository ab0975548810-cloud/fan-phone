"""Read source-order artwork without ever initializing or appending a design version."""
import hashlib
import io
import re

from PIL import Image

from design_sources import read


def export_artwork(app, order_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):
        raise ValueError('訂單識別無效')
    fields=('id','model_id','model_name','style_id','style_name','print_path','mockup_path')
    if app.USE_SUPABASE:
        rows=app.SUPABASE.table('orders').select(','.join(fields)).eq('id',order_id).limit(1).execute().data
        order=next(iter(rows),None)
    else:
        order=app.commerce.store.order(order_id)
    if not order or order['id']!=order_id:
        raise ValueError('找不到來源訂單')
    manifest={field:order[field] for field in fields[1:5]}
    files={}
    for kind,field in [('print','print_path'),('preview','mockup_path')]:
        expected=f'orders/{order_id}/{kind}.png'
        if not app.USE_SUPABASE:
            expected=expected.replace('/','_')
        if order.get(field)!=expected:
            raise ValueError('來源圖檔路徑與訂單不符')
        raw=read(app,expected)
        if len(raw)>48*1024*1024:
            raise ValueError('來源圖檔過大')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.width*image.height>18000000:
                raise ValueError('來源圖片格式或尺寸無效')
            size=image.size
            dpi=image.info.get('dpi',())
            image.verify()
        sha=hashlib.sha256(raw).hexdigest()
        files[sha]=raw
        manifest[kind]=dict(sha256=sha,size=size,dpi=dpi)
    return manifest,files
