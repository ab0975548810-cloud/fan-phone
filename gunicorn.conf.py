import os
import secrets

# These run before app.py is imported by Gunicorn.
# A random fallback secret is safer than a known hard-coded development secret;
# set FLASK_SECRET_KEY in Zeabur for stable sessions across redeploys.
os.environ.setdefault('FLASK_SECRET_KEY', secrets.token_urlsafe(48))
os.environ.setdefault('SESSION_COOKIE_SECURE', 'true')

# One process with multiple threads keeps memory modest while preventing a long
# AI request or several preview images from freezing the whole admin panel.
worker_class = 'gthread'
workers = 1
threads = 4
timeout = 330
graceful_timeout = 30
keepalive = 5


def post_worker_init(worker):
    try:
        import app as app_module
        from security_perf import install
        install(app_module)
        worker.log.info('Benfuwan security/performance middleware installed')
    except Exception:
        worker.log.exception('Failed to install Benfuwan security/performance middleware')
        raise
