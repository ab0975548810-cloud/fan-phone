-- An operator may explicitly attest that an accepted UNKNOWN task is absent
-- from Ruiyin's pending/history/completed views. This is NOT vendor proof.
-- Deployment requires a reviewed backup and this migration BEFORE the app code.
-- No operation here contacts the printer or creates a second print attempt.
create or replace function public.attest_print_unknown_missing(
    p_job_id uuid,
    p_request_key text,
    p_vendor_taskid text,
    p_operator text,
    p_confirmation text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.print_jobs%rowtype;
    v_latest public.print_jobs%rowtype;
    v_existing public.print_events%rowtype;
    v_unsafe boolean;
    v_now timestamptz := now();
    v_key text := 'operator-missing:' || coalesce(p_request_key, '');
    v_note text := '操作員已核對銳印待列印、歷史、完成及實體輸出，確認找不到原 Task ID；'
                    || '此操作有重複出墨風險，原銳印 Task ID 與證據均保留';
begin
    if p_request_key is null or p_request_key !~ '^[A-Za-z0-9_-]{16,100}$'
       or p_confirmation is distinct from 'VERIFIED_RUIYIN_HISTORY_AND_NO_PHYSICAL_OUTPUT'
       or length(coalesce(p_vendor_taskid, '')) < 1
       or length(coalesce(p_operator, '')) not between 1 and 100 then
        return jsonb_build_object('ok', false, 'code', 'BAD_CONFIRMATION');
    end if;

    select * into v_job from public.print_jobs where id = p_job_id;
    if not found then
        return jsonb_build_object('ok', false, 'code', 'JOB_NOT_FOUND');
    end if;

    -- Same per-order lock contract as claim_send, callback and reconcile.
    perform pg_advisory_xact_lock(
        hashtextextended('benfuwan:print-order:' || v_job.order_id, 0));
    perform 1 from public.print_jobs where order_id = v_job.order_id for update;
    select * into v_job from public.print_jobs where id = p_job_id;
    select * into v_latest from public.print_jobs
      where order_id = v_job.order_id order by attempt_no desc limit 1;
    select * into v_existing from public.print_events where event_key = v_key;

    if found then
        if v_existing.job_id <> p_job_id or v_existing.event_type <> 'OPERATOR_CONFIRMED_MISSING'
           or v_existing.payload_json->>'vendor_taskid' is distinct from p_vendor_taskid
           or v_existing.payload_json->>'operator' is distinct from p_operator then
            return jsonb_build_object('ok', false, 'code', 'IDEMPOTENCY_CONFLICT');
        end if;
        return jsonb_build_object('ok', true, 'code', 'OK', 'replay', true,
                                  'job', to_jsonb(v_job), 'latest', to_jsonb(v_latest));
    end if;

    if v_latest.id is distinct from p_job_id then
        return jsonb_build_object('ok', false, 'code', 'STALE_PRINT_ATTEMPT');
    end if;
    if v_job.state <> 'UNKNOWN' or v_job.ambiguous_operation is not null then
        return jsonb_build_object('ok', false, 'code', 'RECONCILE_REQUIRED');
    end if;
    if v_job.vendor_taskid is null or v_job.vendor_taskid <> p_vendor_taskid
       or v_job.sent_at is null then
        return jsonb_build_object('ok', false, 'code', 'BAD_CONFIRMATION');
    end if;
    if v_job.last_reconciled_at is null or v_job.reconcile_count < 1 then
        return jsonb_build_object('ok', false, 'code', 'RECONCILE_REQUIRED');
    end if;

    select exists (
      select 1 from public.print_jobs
       where order_id = v_job.order_id
         and (state in ('PRINTING', 'COMPLETED')
              or vendor_raw_status in ('1', '2')
              or started_at is not null
              or completed_at is not null
              or ambiguous_operation = 'prior_attempt_activity')
    ) into v_unsafe;
    if v_unsafe then
        return jsonb_build_object('ok', false, 'code', 'REPRINT_REQUIRED');
    end if;

    insert into public.print_events
        (id,job_id,event_key,event_type,raw_status,raw_message,payload_json,created_at)
    values (
        gen_random_uuid(), p_job_id, v_key, 'OPERATOR_CONFIRMED_MISSING',
        v_job.vendor_raw_status, left(v_note,500),
        jsonb_build_object(
            'vendor_taskid', p_vendor_taskid,
            'operator', p_operator,
            'confirmation', p_confirmation,
            'reconciled_at', v_job.last_reconciled_at,
            'reconcile_count', v_job.reconcile_count,
            'vendor_lookup', 'no_matching_pending_tasks',
            'original_state', v_job.state,
            'original_attempt_no', v_job.attempt_no,
            'warning', 'Operator attestation is not evidence that vendor never accepted a task'
        ), v_now
    );
    update public.print_jobs
       set state = 'CANCELED', canceled_at = v_now,
           ambiguous_operation = 'operator_confirmed_missing',
           last_error = left(v_note,500), updated_at = v_now
     where id = p_job_id and state = 'UNKNOWN'
     returning * into v_job;

    return jsonb_build_object('ok', true, 'code', 'OK', 'replay', false,
                              'job', to_jsonb(v_job), 'latest', to_jsonb(v_job));
end;
$$;

revoke all on function public.attest_print_unknown_missing(uuid,text,text,text,text)
    from public, anon, authenticated;
grant execute on function public.attest_print_unknown_missing(uuid,text,text,text,text)
    to service_role;
