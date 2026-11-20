"""Private editor process settings. The shop's Gunicorn hook starts real shop services."""
import os

workers=1
worker_class='gthread'
threads=4
bind='0.0.0.0:'+os.environ.get('PORT','8080')
timeout=180
accesslog=None
preload_app=False
