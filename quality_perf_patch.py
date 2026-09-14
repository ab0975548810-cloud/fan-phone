"""Quality/performance patch for large template uploads and high-resolution order PNGs."""
import os
import uuid
from io import BytesIO

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024

    try:
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = 120_000_000
    except Exception:
        Image = None
        ImageOps = None

    original_upload = app_module.upload_public_file

    def _upload_bytes(raw, mime, folder, ext):
        name = f'{folder}/{uuid.uuid4().hex}.{ext}'
        if app_module.USE_SUPABASE:
            app_module.SUPABASE.storage.from_(app_module.SUPABASE_PUBLIC_BUCKET).upload(
                name, raw, file_options={'content-type': mime}
            )
            return app_module._supabase_public_url(name)
        local_dir = app_module.STICKER_DIR if folder == 'stickers' else app_module.MATERIAL_DIR
        os.makedirs(local_dir, exist_ok=True)
        local_name = os.path.basename(name)
        with open(os.path.join(local_dir, local_name), 'wb') as f:
            f.write(raw)
        local_folder = 'stickers' if folder == 'stickers' else 'materials'
        return f'/static/{local_folder}/{local_name}'

    def _optimize_template(raw):
        if not Image:
            return raw, None, None
        with Image.open(BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if w * h > 100_000_000:
                raise ValueError('圖片解析度過大，請使用 1 億畫素以下的圖片')
            has_alpha = 'A' in im.getbands() or 'transparency' in im.info
            if max(w, h) > 5200:
                im.thumbnail((5200, 5200), Image.Resampling.LANCZOS)
            im = im.convert('RGBA' if has_alpha else 'RGB')
            q = 95
            out = BytesIO()
            im.save(out, format='WEBP', quality=q, method=4)
            while out.tell() > 14 * 1024 * 1024 and q > 84:
                q -= 3
                out = BytesIO()
                im.save(out, format='WEBP', quality=q, method=4)
            data = out.getvalue()
            if len(data) > 16 * 1024 * 1024:
                raise ValueError('圖片最佳化後仍過大，請換一張較小的原圖')
            return data, 'image/webp', 'webp'

    def upload_public_file(file_storage, folder):
        if not file_storage or not file_storage.filename:
            raise ValueError('沒有選擇檔案')
        mime = (file_storage.mimetype or '').lower()
        if mime not in ('image/png', 'image/jpeg', 'image/webp'):
            raise ValueError('只允許 PNG / JPG / WEBP 圖片')
        raw = file_storage.read()
        if not raw:
            raise ValueError('圖片內容是空的')
        if len(raw) > 48 * 1024 * 1024:
            raise ValueError('單張原圖需小於 48MB')

        if folder == 'templates' and (len(raw) > 7 * 1024 * 1024 or Image):
            try:
                optimized, new_mime, new_ext = _optimize_template(raw)
                if optimized and new_mime and new_ext:
                    return _upload_bytes(optimized, new_mime, folder, new_ext)
            except ValueError:
                raise
            except Exception as exc:
                print('[QUALITY] template server optimization fallback:', repr(exc), flush=True)

        if len(raw) <= 10 * 1024 * 1024:
            try:
                file_storage.stream.seek(0)
                return original_upload(file_storage, folder)
            except Exception:
                pass

        # Larger masks/materials are preserved as-is; template photos are optimized above.
        if len(raw) > 24 * 1024 * 1024:
            raise ValueError('圖片需小於 24MB')
        ext = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime]
        return _upload_bytes(raw, mime, folder, ext)

    def decode_png_data_url(value, max_bytes=28 * 1024 * 1024):
        import base64
        prefix = 'data:image/png;base64,'
        if not isinstance(value, str) or not value.startswith(prefix):
            raise ValueError('圖片資料格式錯誤')
        try:
            raw = base64.b64decode(value[len(prefix):], validate=True)
        except Exception:
            raise ValueError('圖片 Base64 無法解析')
        if len(raw) > max_bytes:
            raise ValueError('高畫質圖片超過 28MB，請縮小設計後再試')
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('圖片不是有效 PNG')
        return raw

    app_module.upload_public_file = upload_public_file
    app_module.decode_png_data_url = decode_png_data_url
    print('[QUALITY] large template uploads + 28MB production PNG enabled', flush=True)
