import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reedit_private_handoffs import PrivateHandoffs


class HandoffTests(unittest.TestCase):
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
