"""Bounded synthetic workload used only inside the isolated QA service."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Barrier
from time import monotonic

from PIL import Image
from reedit_transport import MAX_BUNDLE, pack, unpack


def measure():
    import resource

    started = monotonic()
    with Image.new('RGBA', (2030, 4241), '#eaaaaa') as image, BytesIO() as encoded:
        image.save(encoded, 'PNG', dpi=(720, 720))
        png = encoded.getvalue()
    padding = bytes(MAX_BUNDLE - len(png) - 128 * 1024)
    digest = sha256(png).hexdigest()
    ref = {'sha256': digest}
    raw = pack({'print': ref, 'preview': ref}, {digest: png, sha256(padding).hexdigest(): padding})
    del padding
    _, files = unpack(raw)
    count = len(raw)
    del raw, files
    barrier = Barrier(2)

    def decode(_):
        with Image.open(BytesIO(png)) as im:
            im.load()
            barrier.wait(timeout=15)
            return list(im.size)

    with ThreadPoolExecutor(max_workers=2) as executor:
        sizes = list(executor.map(decode, range(2)))
    try:
        unpack(bytes(MAX_BUNDLE + 1))
    except ValueError:
        rejected = True
    else:
        raise AssertionError('Oversized transfer accepted')
    peak = Path('/sys/fs/cgroup/memory.peak')
    return dict(bundle_bytes=count, limit_bytes=MAX_BUNDLE, oversized_rejected=rejected,
                concurrent_decode=sizes, elapsed_seconds=round(monotonic()-started, 3),
                worker_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                container_peak_bytes=int(peak.read_text()) if peak.exists() else None)


def verify_restore(volume, sid):
    """Rehearse offline recovery on a disposable copy while issuance is disabled."""
    import json
    import shutil
    import sqlite3
    import tempfile
    import time
    from contextlib import closing
    from reedit_private_site import cleanup, TTL

    with closing(sqlite3.connect(volume/'access.db')) as access:
        if not access.execute('select 1 from controls where disabled=1').fetchone():
            raise ValueError('Pause QA before rehearsing a restore')
        with tempfile.TemporaryDirectory(dir=volume) as name:
            restored = Path(name)
            with closing(sqlite3.connect(restored/'access.db')) as dest:
                access.backup(dest)
            shutil.copytree(volume/sid, restored/sid)
            cleanup(restored, revoke=True)
            with closing(sqlite3.connect(restored/'access.db')) as db:
                assert db.execute('select count(*) from handoffs').fetchone()[0] == 0
                assert db.execute('select disabled from controls where id=1').fetchone() == (1,)
            manifest = json.loads((restored/sid/'manifest.json').read_text())
            digest = manifest['print']['sha256']
            if sha256((restored/sid/digest).read_bytes()).hexdigest() != digest:
                raise ValueError('Restored art did not match')
            with closing(sqlite3.connect(restored/sid/'work.db')) as db:
                orders = db.execute('select count(*) from made').fetchone()[0]
            cleanup(restored, now=time.time()+TTL+1)
            if (restored/sid).exists():
                raise ValueError('Expired artwork survived cleanup')
            return dict(orders=orders, original_verified=True, grants_revoked=True, expired_removed=True)
