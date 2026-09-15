"""Runtime tuning for scale-to-zero AI background-removal jobs.

The production Runpod endpoint uses Active workers=0 so idle time costs nothing.
A cold worker may need time to pull/start the image and load BiRefNet before the
first request can run. Give that first request enough time instead of failing at
75 seconds; warm requests still return as soon as they finish.
"""

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Scale-to-zero can occasionally need more than 75s for a true cold start.
    # 180s is still bounded, while avoiding false failures in both storefront
    # and admin. The backend cancels the Runpod job if this deadline is reached.
    try:
        configured = int(app_module.AI_REMOVE_BG_TIMEOUT or 180)
        app_module.AI_REMOVE_BG_TIMEOUT = max(120, min(configured, 180))
    except Exception:
        app_module.AI_REMOVE_BG_TIMEOUT = 180

    try:
        app_module.AI_POLL_INTERVAL = min(float(app_module.AI_POLL_INTERVAL or 1.5), 1.5)
    except Exception:
        app_module.AI_POLL_INTERVAL = 1.5

    print(
        f'[AI] scale-to-zero runtime tuned: remove-bg timeout={app_module.AI_REMOVE_BG_TIMEOUT}s '
        f'poll={app_module.AI_POLL_INTERVAL}s',
        flush=True,
    )
