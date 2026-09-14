"""Runtime tuning for AI jobs.

Keep customer-facing requests from hanging for several minutes. The normal
BiRefNet endpoint should finish quickly once the lightweight worker is warm;
if it does not, fail clearly and let the user retry instead of blocking the UI.
"""

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # 75 seconds is long enough for a normal scale-to-zero BiRefNet cold start,
    # but short enough that the storefront never looks permanently frozen.
    try:
        app_module.AI_REMOVE_BG_TIMEOUT = min(int(app_module.AI_REMOVE_BG_TIMEOUT or 75), 75)
    except Exception:
        app_module.AI_REMOVE_BG_TIMEOUT = 75

    try:
        app_module.AI_POLL_INTERVAL = min(float(app_module.AI_POLL_INTERVAL or 1.5), 1.5)
    except Exception:
        app_module.AI_POLL_INTERVAL = 1.5

    print(
        f'[AI] runtime tuned: remove-bg timeout={app_module.AI_REMOVE_BG_TIMEOUT}s '
        f'poll={app_module.AI_POLL_INTERVAL}s',
        flush=True,
    )
