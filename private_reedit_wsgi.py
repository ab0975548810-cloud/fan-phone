"""Entry point for the dedicated Railway private editor service and scheduled cleanup."""
import os
from pathlib import Path
import sys
import threading
import logging

from reedit_private_site import cleanup, create_private_site

volume = Path('/private-reedit')
if (os.environ.get('RAILWAY_PROJECT_ID')!='62673372-609e-4fc2-b86f-c0e75b46fdaa'
        or os.environ.get('RAILWAY_ENVIRONMENT_ID')!='49f531ce-e0ae-46e9-b37f-55e08218eb42'
        or not os.getenv('RAILWAY_SERVICE_ID') or os.getenv('RAILWAY_SERVICE_ID')=='6bf54261-6c00-49fa-a819-89c8ba029c0f'
        or not os.path.ismount(volume)
        or any(os.getenv(k) for k in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','DATABASE_URL',
                                     'ADMIN_PASSWORD','YUN_PRINT_DEVICE_KEY','YUN_PRINT_DEVICE_ID'))):
    raise RuntimeError('Dedicated private QA environment and volume required')
app=create_private_site(volume,os.environ['PRIVATE_REEDIT_SESSION_SECRET'])
def janitor():
    timer=threading.Event()
    while not timer.wait(60):
        try:
            cleanup(volume)
        except Exception:
            logging.getLogger(__name__).error('private snapshot cleanup failed')


if __name__!='__main__':
    cleanup(volume)
    threading.Thread(target=janitor,name='private-retention',daemon=True).start()

if __name__=='__main__':
    if sys.argv[1:] not in (['cleanup'],['revoke']):
        raise SystemExit('Expected cleanup or revoke')
    cleanup(volume,revoke=sys.argv[1:] == ['revoke'])
