"""Atomic version approval and independent reprint; never dispatches a vendor call."""
import json
import uuid
from order_designs import digest
from print_store import ACTIVE_STATES, BOOL_COLUMNS, utcnow
from pixel_order_designs import FIELDS


def authorize(app, order_id, revision, actor, reason, cost):
    store=app.print_center.store;d=revision['document']
    key='pixel-'+digest([order_id,revision['version'],revision['content_hash']])[:64]
    args={'p_order':order_id,'p_version':revision['version'],'p_hash':revision['content_hash'],
          'p_key':key,'p_actor':actor,'p_reason':reason,'p_cost':cost}
    if app.USE_SUPABASE:return app.SUPABASE.rpc('approve_pixel_reprint',args).execute().data
    with store.connection(True) as db:
        # The existing print-center profile action must not replace the approved
        # historical geometry, including when it races the send claim.
        immutable=FIELDS+('artwork_path','artwork_sha256','manual_independent')
        changed=' OR '.join(f'NEW.{k} IS NOT OLD.{k}' for k in immutable)
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS pixel_reprint_geometry_immutable
            BEFORE UPDATE ON print_jobs WHEN ({changed}) AND EXISTS (
                SELECT 1 FROM print_events WHERE job_id=OLD.id
                AND event_type='MANUAL_REPRINT_AUTHORIZED'
                AND json_extract(payload_json,'$.versionHash') IS NOT NULL)
            BEGIN SELECT RAISE(ABORT,'Approved pixel reprint geometry is immutable'); END""")
        prior=db.execute('SELECT * FROM print_requests WHERE request_key=?',(key,)).fetchone()
        if prior:return {'ok':prior['request_hash']==revision['content_hash'],'job':store._decode(db.execute('SELECT * FROM print_jobs WHERE id=?',(prior['job_id'],)).fetchone())}
        latest=db.execute('SELECT max(version) FROM order_design_versions WHERE order_id=?',(order_id,)).fetchone()[0]
        if latest!=revision['version']:return {'ok':False}
        jobs=[dict(r) for r in db.execute('SELECT * FROM print_jobs WHERE order_id=?',(order_id,))]
        if any(j['state'] in ACTIVE_STATES or j.get('ambiguous_operation') for j in jobs):return {'ok':False}
        source=next((j for j in jobs if j['id']==d['profile']['sourceJobId']),None)
        if not source or source['artwork_sha256']!=d['baseSha'] or any(source[k]!=d['profile'][k] for k in FIELDS):return {'ok':False}
        now=utcnow();job=dict(source)
        for k in ('vendor_taskid','vendor_raw_status','vendor_raw_message','ambiguous_operation','last_error','device_id','last_reconciled_at','sent_at','started_at','completed_at','canceled_at','artwork_token_expires_at'):job[k]=None
        job.update(id=str(uuid.uuid4()),manual_independent=True,attempt_no=max(j['attempt_no'] for j in jobs)+1,
                   state='PREPARED',artwork_path=d['outputPath'],artwork_sha256=d['outputSha'],
                   artwork_token_nonce=uuid.uuid4().hex,created_at=now,updated_at=now,prepared_at=now,reconcile_count=0)
        db.execute(f"INSERT INTO print_jobs ({','.join(job)}) VALUES ({','.join('?' for _ in job)})",[int(v) if k in BOOL_COLUMNS else v for k,v in job.items()])
        audit={'actor':actor,'version':revision['version'],'versionHash':revision['content_hash'],'reason':reason,'costCents':cost,'sourceJobId':source['id'],'baseSha':d['baseSha'],'outputSha':d['outputSha'],'parameters':d['profile']}
        db.execute('INSERT INTO print_events (id,job_id,event_key,event_type,raw_status,raw_message,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
                   (str(uuid.uuid4()),job['id'],key,'MANUAL_REPRINT_AUTHORIZED',None,'已比較 V1／V2，人工確認像素修補重印',json.dumps(audit),now))
        db.execute('INSERT INTO print_requests VALUES (?,?,?,?,?,?,?,?)',(key,'pixel_reprint',job['id'],revision['content_hash'],'COMPLETED',json.dumps({'job_id':job['id']}),now,now))
        return {'ok':True,'job':job}
