"""Bounded transport retries for immutable, private production artwork reads.

The pinned Storage SDK uses a 20-second network inactivity timeout. Reserve that
window before every additional GET, within a 60-second retry budget. This is not
a hard deadline for a server that continues streaming bytes. No shared client
settings, upload, deletion, or vendor requests are changed here.
"""
import time

from httpx import TransportError


_RETRY_DELAYS = (0.2, 0.4)
_SDK_READ_WINDOW = 20.0
_RETRY_BUDGET = 60.0


def download_artwork(app, path):
    deadline = time.monotonic() + _RETRY_BUDGET
    bucket = app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET)
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return bucket.download(path)
        except TransportError as exc:
            if attempt == len(_RETRY_DELAYS):
                raise
            delay = _RETRY_DELAYS[attempt]
            if time.monotonic() + delay + _SDK_READ_WINDOW > deadline:
                raise
            # Exception messages/URLs may contain private paths or credentials.
            app.app.logger.warning(
                'production_storage_get_retry attempt=%d error=%s',
                attempt + 2, type(exc).__name__,
            )
            time.sleep(delay)
