"""Server-rendered admin shell using the shared editor controls and runtime."""
from functools import lru_cache
from html import escape
import re

from editable_stickers import ROOT


EDITOR_SCRIPTS = {
    'front-v22-fixes.js', 'product-catalog-v1.js', 'front-model-profile.js', 'front-editor-ux.js',
    'front-ai-context.js', 'front-outline-styles.js', 'front-outline-slider-fix.js',
    'front-outline-no-flash.js', 'editor-image-loader.js', 'front-sticker-categories.js',
    'front-print-mask.js', 'front-production-hq.js', 'front-image-upload.js', 'front-editor-history-v2.js',
    'ai-remove-client-v2.js', 'ai-interactive-core-v1.js', 'front-ai-remove-v2.js',
    'front-editor-access-v1.js', 'design-source-upload-v1.js', 'editable-sticker-core-v1.js',
    'front-editable-stickers-v1.js', 'multilayer-template-core-v1.js',
    'multilayer-template-v1.css', 'front-multilayer-template-v1.js',
    'front-editor-controls-v1.js', 'order-revision-review-v1.js',
    'pixel-order-recovery-v1.js', 'front-pixel-order-v1.js', 'front-order-design-v1.js',
}


@lru_cache(maxsize=1)
def workspace_html():
    source = (ROOT / 'static/index-base-20260913.html').read_text(encoding='utf-8')
    loader = (ROOT / 'index.html').read_text(encoding='utf-8')
    head = source.split('</head>', 1)[0]
    head = head.replace('<title>本福丸訂製｜客製手機殼 DIY</title>', '<title>訂單設計工作區｜本福丸</title>')
    head = head.replace('https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js',
                        '/static/vendor/fabric-5.3.1.min.js')
    head += """<style>
      #workspace-loading { padding:16px }
      .admin-order-design-workspace .app { max-width:780px }
      #order-alignment-controls { border:0; margin:0; padding:0 }
      #order-alignment-controls p { margin:4px 0 }
      #order-alignment-controls label { display:inline-flex; align-items:center; gap:5px; margin-right:10px }
      .order-existing-alignment #phone-mask,
      .order-existing-alignment #print-area-guide,
      .order-existing-alignment #safe-guide { opacity:var(--order-guide-opacity,.65)!important }
    </style>"""
    head = head.replace('href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">',
                        'href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" media="print" onload="this.media=&#39;all&#39;">')
    head = re.sub(r'<link[^>]+front-home-v1\.css[^>]+>\s*', '', head)
    editor = source.split('<!-- EDITOR -->', 1)[1].split('<!-- CART -->', 1)[0]
    editor = editor.replace('<i class="fa-solid fa-chevron-left"></i></button>', '<span aria-hidden="true">‹</span></button>')
    editor = editor.replace('onclick="navBack()"', 'onclick="navBack()" aria-label="返回"')
    editor = editor.replace(' 加入購物車</button>', ' 儲存修改</button>')
    editor = re.sub(r'<div class="editor-float right">.*?</div>', '', editor, count=1)
    sheets = source.split('<!-- SHEETS -->', 1)[1].split('</body>', 1)[0]
    modules = []
    for src in re.findall(r'(?:src|href)="(/static/[^"]+)"', loader):
        filename = src.split('?', 1)[0].rsplit('/', 1)[-1]
        if filename in EDITOR_SCRIPTS:
            if filename in ('front-pixel-order-v1.js', 'front-order-design-v1.js'):
                src += '&workspace=1'
            src = escape(src, quote=True)
            if filename.endswith('.css'):
                modules.append(f'<link rel="stylesheet" href="{src}">')
            else:
                modules.append(f'<script src="{src}"></script>')
    if len(modules) != len(EDITOR_SCRIPTS):
        raise RuntimeError('Order workspace editor modules are missing')
    modules.insert(0, '<script src="/static/admin-order-design-workspace.js?v=1"></script>')
    return (head + '</head><body class="admin-order-design-workspace">'
            '<script>window.__bfOrderDesignMode=true;window.__bfOrderWorkspace=true;</script>'
            '<main id="workspace-loading" role="status">正在開啟訂單設計…</main>'
            '<div class="app" id="app">' + editor + sheets + '\n'.join(modules) + '</body></html>')
