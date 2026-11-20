import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reedit_private_handoffs import PrivateHandoffs


class HandoffTests(unittest.TestCase):
    def test_readonly_snapshot_and_private_field_filter(self):
        import io
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PIL import Image
        from reedit_snapshot import export_artwork
        with tempfile.TemporaryDirectory() as folder:
            buf=io.BytesIO()
            Image.new('RGBA',(30,60)).save(buf,format='PNG',dpi=(720,720))
            row=dict(id='A',model_id='m',model_name='model',style_id='s',style_name='case',
                     print_path='orders_A_print.png',mockup_path='orders_A_preview.png',customer_name='private')
            for key in ('print_path','mockup_path'):
                (Path(folder)/row[key]).write_bytes(buf.getvalue())
            def disk():return {p.name:p.read_bytes() for p in Path(folder).iterdir()}
            before=disk()
            store=Mock()
            store.order.return_value=row
            app=SimpleNamespace(USE_SUPABASE=False,SAVE_DIR=folder,commerce=SimpleNamespace(store=store))
            manifest,assets=export_artwork(app,'A')
            self.assertNotIn('customer_name',manifest)
            self.assertEqual(assets[manifest['print']['sha256']],buf.getvalue())
            store.order.assert_called_once_with('A')
            self.assertEqual(disk(),before)
            row['mockup_path']='orders_B_preview.png'
            with self.assertRaises(ValueError):export_artwork(app,'A')

    def test_concurrent_redeem_and_disable(self):
        with tempfile.TemporaryDirectory() as folder:
            active={'owner','other'}
            now=[100]
            store=PrivateHandoffs(Path(folder)/'qa.db',active.__contains__,lambda:now[0])
            code=store.issue('owner','snapshot-A')
            with self.assertRaises(PermissionError):
                store.redeem(code,'other')
            def redeem(_):
                try:return store.redeem(code,'owner')
                except PermissionError:return None
            with ThreadPoolExecutor(4) as threads:
                tokens=list(filter(None,threads.map(redeem,range(4))))
            self.assertEqual(len(tokens),1)
            self.assertEqual(store.access(tokens[0],'snapshot-A'),'owner')
            with self.assertRaises(PermissionError):
                store.access(tokens[0],'snapshot-B')
            pending=store.issue('owner','snapshot-C')
            active.clear()
            with self.assertRaises(PermissionError):store.access(tokens[0],'snapshot-A')
            with self.assertRaises(PermissionError):store.redeem(pending,'owner')
            with self.assertRaises(PermissionError):store.issue('owner','snapshot-D')
            now[0]+=46
            active.add('owner')
            with self.assertRaises(PermissionError):store.redeem(pending,'owner')


if __name__=='__main__':unittest.main()
