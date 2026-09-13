import os
import secrets

# These run before app.py is imported by Gunicorn.
# A random fallback secret is safer than a known hard-coded development secret;
# set FLASK_SECRET_KEY in Zeabur for stable sessions across redeploys.
if not (os.environ.get('FLASK_SECRET_KEY') or '').strip():
    os.environ['FLASK_SECRET_KEY'] = secrets.token_urlsafe(48)
    os.environ['BENFUWAN_GENERATED_SECRET'] = '1'
else:
    os.environ['BENFUWAN_GENERATED_SECRET'] = '0'
if not (os.environ.get('SESSION_COOKIE_SECURE') or '').strip():
    os.environ['SESSION_COOKIE_SECURE'] = 'true'

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
        from security_perf import install as install_security
        from supabase_resilience import install as install_supabase_resilience
        from admin_perf_patch import install as install_admin_perf
        install_security(app_module)
        install_supabase_resilience(app_module)
        install_admin_perf(app_module)
        worker.log.info('Benfuwan security/performance middleware installed')
    except Exception:
        worker.log.exception('Failed to install Benfuwan security/performance middleware')
        raise
