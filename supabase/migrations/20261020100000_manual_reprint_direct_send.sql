-- Explicit operator-authorized reprint. Apply only after a restorable backup.
-- This does not enable the vendor integration and never calls startPrint/pushPrint.

alter table public.print_requests
    drop constraint if exists print_requests_operation_check;
alter table public.print_requests
    add constraint print_requests_operation_check check (operation in (
        'prepare','send','start','cancel','reconcile','profile_snapshot','manual_reprint'
    ));

create or replace function public.authorize_manual_reprint(
    p_order_id text,
    p_request_key text,
    p_request_hash text,
    p_actor text,
    p_order_status text,
    p_seed jsonb,
    p_handoff_review boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_request public.print_requests%rowtype;
    v_latest public.print_jobs%rowtype;
    v_active public.print_jobs%rowtype;
    v_job public.print_jobs%rowtype;
    v_authorized boolean := false;
    v_prior_physical boolean := false;
    v_event_type text;
    v_payload jsonb;
begin
    if p_order_id is null or p_order_id !~ '^[A-Za-z0-9-]{1,100}$'
       or p_request_key is null or p_request_key !~ '^[A-Za-z0-9_-]{16,100}$'
       or p_request_hash is null or length(p_request_hash) < 16
       or nullif(left(coalesce(p_actor, ''), 100), '') is null then
        return jsonb_build_object('ok', false, 'code', 'BAD_REQUEST');
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('benfuwan:print-order:' || p_order_id, 0));
    perform 1 from public.print_jobs where order_id = p_order_id for update;

    select * into v_request from public.print_requests
     where request_key = p_request_key for update;
    if found then
        if v_request.operation <> 'manual_reprint'
           or v_request.request_hash <> p_request_hash then
            return jsonb_build_object('ok', false, 'code', 'IDEMPOTENCY_CONFLICT');
        end if;
        select * into v_job from public.print_jobs where id = v_request.job_id;
        if not found then
            return jsonb_build_object('ok', false, 'code', 'JOB_NOT_FOUND');
        end if;
        return jsonb_build_object('ok', true, 'code', 'OK', 'replay', true,
                                  'job', to_jsonb(v_job));
    end if;

    select * into v_latest from public.print_jobs
     where order_id = p_order_id order by attempt_no desc limit 1;
    select * into v_active from public.print_jobs
     where order_id = p_order_id
       and state in ('PREPARED','SENDING','QUEUED','STARTING','PRINTING','CANCELING','UNKNOWN')
     order by attempt_no desc limit 1;
    if found and v_active.state <> 'PREPARED' then
        return jsonb_build_object(
            'ok', false,
            'code', case when v_active.state in ('SENDING','UNKNOWN')
                         then 'RECONCILE_REQUIRED' else 'ACTIVE_PRINT_JOB' end);
    end if;

    if v_active.id is not null then
        select exists (
            select 1 from public.print_events
             where job_id = v_active.id and event_type in (
                 'MANUAL_REPRINT_AUTHORIZED',
                 'HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED'
             )
        ) into v_authorized;
        select exists (
            select 1 from public.print_jobs
             where order_id = p_order_id and id <> v_active.id and (
                 state in ('PRINTING','COMPLETED')
                 or vendor_raw_status in ('1','2')
                 or started_at is not null or completed_at is not null
                 or ambiguous_operation = 'prior_attempt_activity'
             )
        ) into v_prior_physical;
        if v_active.ambiguous_operation is not null
           or (v_prior_physical and not v_authorized) then
            return jsonb_build_object('ok', false, 'code', 'RECONCILE_REQUIRED');
        end if;
        v_job := v_active;
    else
        if v_latest.id is not null and (
            nullif(v_latest.artwork_path, '') is null
            or nullif(v_latest.artwork_sha256, '') is null
            or nullif(v_latest.sku_id, '') is null
            or not v_latest.profile_complete
            or v_latest.width_mm is null or v_latest.height_mm is null
            or v_latest.left_mm is null or v_latest.top_mm is null
            or v_latest.copies is null or v_latest.spot_color is null
            or v_latest.channel is null or v_latest.angle is null
        ) then
            return jsonb_build_object('ok', false, 'code', 'PROFILE_MISSING');
        end if;
        if v_latest.id is null and (
            p_seed is null
            or nullif(p_seed->>'artwork_path', '') is null
            or nullif(p_seed->>'artwork_sha256', '') is null
            or nullif(p_seed->>'sku_id', '') is null
            or p_seed->>'width_mm' is null or p_seed->>'height_mm' is null
            or p_seed->>'left_mm' is null or p_seed->>'top_mm' is null
            or p_seed->>'copies' is null or p_seed->>'spot_color' is null
            or p_seed->>'channel' is null or p_seed->>'angle' is null
        ) then
            return jsonb_build_object('ok', false, 'code', 'PROFILE_MISSING');
        end if;

        insert into public.print_jobs (
            id,order_id,attempt_no,sku_id,vendor_taskid,artwork_path,artwork_sha256,
            artwork_token_nonce,artwork_token_expires_at,profile_complete,
            width_mm,height_mm,left_mm,top_mm,copies,spot_color,channel,angle,
            device_id,state,vendor_raw_status,vendor_raw_message,ambiguous_operation,
            last_error,reconcile_count,last_reconciled_at,created_at,updated_at,
            prepared_at,sent_at,started_at,completed_at,canceled_at
        ) values (
            gen_random_uuid(), p_order_id, coalesce(v_latest.attempt_no, 0) + 1,
            coalesce(v_latest.sku_id, p_seed->>'sku_id'), null,
            coalesce(v_latest.artwork_path, p_seed->>'artwork_path'),
            coalesce(v_latest.artwork_sha256, p_seed->>'artwork_sha256'),
            coalesce(nullif(p_seed->>'artwork_token_nonce',''), gen_random_uuid()::text),
            null, coalesce(v_latest.profile_complete, true),
            coalesce(v_latest.width_mm, (p_seed->>'width_mm')::numeric),
            coalesce(v_latest.height_mm, (p_seed->>'height_mm')::numeric),
            coalesce(v_latest.left_mm, (p_seed->>'left_mm')::numeric),
            coalesce(v_latest.top_mm, (p_seed->>'top_mm')::numeric),
            coalesce(v_latest.copies, (p_seed->>'copies')::integer),
            coalesce(v_latest.spot_color, p_seed->>'spot_color'),
            coalesce(v_latest.channel, p_seed->>'channel'),
            coalesce(v_latest.angle, (p_seed->>'angle')::numeric),
            null,'PREPARED',null,null,null,null,0,null,now(),now(),now(),null,null,null,null
        ) returning * into v_job;
    end if;

    v_event_type := case when coalesce(p_handoff_review, false)
        then 'HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED'
        else 'MANUAL_REPRINT_AUTHORIZED' end;
    v_payload := jsonb_build_object(
        'actor', left(p_actor, 100), 'order_id', p_order_id,
        'order_status', coalesce(p_order_status, ''),
        'source_job_id', v_latest.id, 'source_attempt_no', v_latest.attempt_no,
        'source_state', v_latest.state,
        'handoff_review', coalesce(p_handoff_review, false),
        'artwork_sha256', v_job.artwork_sha256,
        'parameters', jsonb_build_object(
            'width_mm',v_job.width_mm,'height_mm',v_job.height_mm,
            'left_mm',v_job.left_mm,'top_mm',v_job.top_mm,'copies',v_job.copies,
            'spot_color',v_job.spot_color,'channel',v_job.channel,'angle',v_job.angle));
    insert into public.print_events (
        id,job_id,event_key,event_type,raw_status,raw_message,payload_json,created_at
    ) values (
        gen_random_uuid(),v_job.id,'manual-reprint:' || p_request_key,v_event_type,
        v_latest.vendor_raw_status,'店員按下重新送任務，已授權建立獨立人工重印嘗試',
        v_payload,now());
    insert into public.print_requests (
        request_key,operation,job_id,request_hash,status,response_json,created_at,updated_at
    ) values (
        p_request_key,'manual_reprint',v_job.id,p_request_hash,'COMPLETED',
        jsonb_build_object('job_id',v_job.id),now(),now());
    return jsonb_build_object('ok', true, 'code', 'OK', 'replay', false,
                              'job', to_jsonb(v_job));
exception
    when unique_violation then
        select * into v_request from public.print_requests
         where request_key = p_request_key;
        if found and v_request.operation = 'manual_reprint'
           and v_request.request_hash = p_request_hash then
            select * into v_job from public.print_jobs where id = v_request.job_id;
            return jsonb_build_object('ok', true, 'code', 'OK', 'replay', true,
                                      'job', to_jsonb(v_job));
        end if;
        return jsonb_build_object('ok', false, 'code', 'CONCURRENT_OPERATION');
end;
$$;

create or replace function public.claim_manual_reprint_send_if_safe(
    p_job_id uuid,
    p_artwork_token_nonce text,
    p_artwork_token_expires_at timestamptz,
    p_device_id text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.print_jobs%rowtype;
    v_latest public.print_jobs%rowtype;
begin
    select * into v_job from public.print_jobs where id = p_job_id;
    if not found then
        return jsonb_build_object('ok', false, 'code', 'JOB_NOT_FOUND');
    end if;
    perform pg_advisory_xact_lock(
        hashtextextended('benfuwan:print-order:' || v_job.order_id, 0));
    perform 1 from public.print_jobs where order_id = v_job.order_id for update;
    select * into v_job from public.print_jobs where id = p_job_id;
    select * into v_latest from public.print_jobs
     where order_id = v_job.order_id order by attempt_no desc limit 1;
    if not exists (
        select 1 from public.print_events where job_id = p_job_id
         and event_type in ('MANUAL_REPRINT_AUTHORIZED',
                            'HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED')
    ) then
        return jsonb_build_object('ok', false, 'code', 'MANUAL_REPRINT_AUTH_REQUIRED');
    end if;
    if v_latest.id <> p_job_id then
        return jsonb_build_object('ok', false, 'code', 'STALE_PRINT_ATTEMPT');
    end if;
    if v_job.state <> 'PREPARED' or v_job.ambiguous_operation is not null then
        return jsonb_build_object(
            'ok', false,
            'code', case when v_job.state in ('SENDING','UNKNOWN')
                              or v_job.ambiguous_operation is not null
                         then 'RECONCILE_REQUIRED' else 'CONCURRENT_OPERATION' end);
    end if;
    update public.print_jobs
       set state='SENDING', artwork_token_nonce=p_artwork_token_nonce,
           artwork_token_expires_at=p_artwork_token_expires_at,
           device_id=p_device_id, last_error=null, ambiguous_operation=null,
           updated_at=now()
     where id=p_job_id and state='PREPARED'
     returning * into v_job;
    return jsonb_build_object('ok', true, 'code', 'OK', 'job', to_jsonb(v_job));
end;
$$;

revoke all on function public.authorize_manual_reprint(text,text,text,text,text,jsonb,boolean)
    from public, anon, authenticated;
revoke all on function public.claim_manual_reprint_send_if_safe(uuid,text,timestamptz,text)
    from public, anon, authenticated;
grant execute on function public.authorize_manual_reprint(text,text,text,text,text,jsonb,boolean)
    to service_role;
grant execute on function public.claim_manual_reprint_send_if_safe(uuid,text,timestamptz,text)
    to service_role;
