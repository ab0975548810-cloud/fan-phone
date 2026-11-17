"""Synthetic historical backup for isolated browser tests, never production data."""
import copy
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from order_designs import asset_paths, digest


@contextmanager
def history_order(app, order, png):
    legacy=copy.deepcopy(order);design=legacy['design_json']
    with tempfile.TemporaryDirectory() as root:
        folder=Path(root)/order['id'];folder.mkdir()
        mapping={path:str(i)+'.png' for i,path in enumerate(sorted(asset_paths(design)))}
        assets={}
        for path,name in mapping.items():
            raw=app.print_center._download_artwork(path)
            (folder/name).write_bytes(raw);assets[name]=hashlib.sha256(raw).hexdigest()
        metadata={key:design.pop(key) for key in ('logicalCanvas','production','editorContext','fontHashes')}
        design.pop('render_contract_version');design.pop('orderDesignVersion')
        metadata['production']['maskPath']=mapping[metadata['production']['maskPath']]
        metadata['editorContext']['previewPath']=mapping[metadata['editorContext']['previewPath']]
        manifest={**metadata,'orderId':order['id'],'originalDesignHash':digest(design),
                  'originalPrintHash':hashlib.sha256(png).hexdigest(),'archiveReference':'synthetic-isolated-backup',
                  'archivedAt':'2026-01-01','sourceMap':mapping,'assets':assets}
        (folder/'manifest.json').write_text(json.dumps(manifest),'utf-8')
        original_get=app.commerce.store.order
        with mock.patch.dict(os.environ,{'ORDER_DESIGN_HISTORY_DIR':root}), \
             mock.patch.object(app.commerce.store,'order',side_effect=lambda key:copy.deepcopy(legacy) if key==order['id'] else original_get(key)), \
             mock.patch('legacy_order_designs.read',return_value=png):
            yield legacy
