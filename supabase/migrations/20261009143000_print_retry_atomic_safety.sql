-- Serialize send claims and superseded callbacks per customer order.
-- Apply only after review and a restorable production backup.

create or replace function public.claim_print_send_if_safe(
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
    v_unsafe boolean;
begin
    select * into v_job from public.print_jobs where id = p_job_id;
    if not found then
        return jsonb_build_object('ok', false, 'code', 'JOB_NOT_FOUND');
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('benfuwan:print-order:' || v_job.order_id, 0));
    select * into v_job from public.print_jobs where id = p_job_id for update;
    perform 1 from public.print_jobs where order_id = v_job.order_id for update;

    select exists (
        select 1 from public.print_jobs
        where order_id = v_job.order_id
          and (
              state in ('PRINTING', 'COMPLETED')
              or vendor_raw_status in ('1', '2')
              or started_at is not null
              or completed_at is not null
              or ambiguous_operation = 'prior_attempt_activity'
          )
    ) into v_unsafe;
    if v_unsafe then
        return jsonb_build_object('ok', false, 'code', 'REPRINT_REQUIRED');
    end if;
    if v_job.state <> 'PREPARED' then
        return jsonb_build_object('ok', false, 'code', 'CONCURRENT_OPERATION');
    end if;

    update public.print_jobs
       set state = 'SENDING',
           artwork_token_nonce = p_artwork_token_nonce,
           artwork_token_expires_at = p_artwork_token_expires_at,
           device_id = p_device_id,
           last_error = null,
           ambiguous_operation = null,
           updated_at = now()
     where id = p_job_id
     returning * into v_job;
    return jsonb_build_object('ok', true, 'code', 'OK', 'job', to_jsonb(v_job));
end;
$$;

create or replace function public.apply_print_callback_safely(
    p_job_id uuid,
    p_status text,
    p_message text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.print_jobs%rowtype;
    v_latest public.print_jobs%rowtype;
    v_superseded boolean;
    v_physical boolean;
    v_raw_status text;
    v_raw_message text;
    v_next_state text;
    v_now timestamptz := now();
    v_warning text := '舊列印嘗試延遲回報列印中/完成，為避免重複打印，本次重推已封鎖';
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
    v_superseded := v_job.attempt_no < v_latest.attempt_no;
    v_raw_status := p_status;
    v_raw_message := left(coalesce(p_message, ''), 500);

    if v_superseded and (
        v_job.vendor_raw_status = '2'
        or (v_job.vendor_raw_status = '1' and p_status <> '2')
    ) then
        v_raw_status := v_job.vendor_raw_status;
        v_raw_message := left(coalesce(v_job.vendor_raw_message, ''), 500);
    end if;

    v_next_state := v_job.state;
    if not v_superseded then
        if v_job.state = 'COMPLETED' then
            null;
        elsif v_job.state = 'CANCELED' and p_status <> '2' then
            null;
        elsif p_status = '1' then v_next_state := 'PRINTING';
        elsif p_status = '2' then v_next_state := 'COMPLETED';
        elsif p_status = '3' then v_next_state := 'CANCELED';
        elsif p_status in ('4','5','6','7','8','11') then v_next_state := 'FAILED';
        elsif p_status <> '12' then v_next_state := 'UNKNOWN';
        end if;
    end if;

    update public.print_jobs
       set vendor_raw_status = v_raw_status,
           vendor_raw_message = v_raw_message,
           state = v_next_state,
           started_at = case when p_status = '1' then coalesce(started_at, v_now) else started_at end,
           completed_at = case when p_status = '2' then coalesce(completed_at, v_now) else completed_at end,
           canceled_at = case when p_status = '3' then coalesce(canceled_at, v_now) else canceled_at end,
           last_error = case
               when not v_superseded and p_status not in ('1','2','3','4','5','6','7','8','11','12')
               then '收到未識別的雲打印狀態'
               else last_error end,
           updated_at = v_now
     where id = p_job_id
     returning * into v_job;

    v_physical := p_status in ('1', '2')
        or v_job.vendor_raw_status in ('1', '2')
        or v_job.started_at is not null
        or v_job.completed_at is not null;
    if v_superseded and v_physical then
        if v_latest.state = 'PREPARED' then
            update public.print_jobs
               set state = 'CANCELED', canceled_at = v_now,
                   ambiguous_operation = 'prior_attempt_activity',
                   last_error = v_warning, updated_at = v_now
             where id = v_latest.id and state = 'PREPARED';
        elsif v_latest.state in (
            'SENDING','QUEUED','STARTING','PRINTING','CANCELING','UNKNOWN'
        ) then
            update public.print_jobs
               set state = 'UNKNOWN',
                   ambiguous_operation = 'prior_attempt_activity',
                   last_error = v_warning || '，請人工查核雲端狀態',
                   updated_at = v_now
             where id = v_latest.id;
        end if;
    end if;

    return jsonb_build_object(
        'ok', true, 'job', to_jsonb(v_job), 'superseded', v_superseded);
end;
$$;

create or replace function public.apply_print_reconcile_safely(
    p_job_id uuid,
    p_matched boolean,
    p_taskid text,
    p_status text,
    p_message text,
    p_ambiguous boolean
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.print_jobs%rowtype;
    v_safe_match boolean := coalesce(p_matched, false);
    v_ambiguous boolean := coalesce(p_ambiguous, false);
    v_quarantined boolean;
    v_next_state text;
    v_now timestamptz := now();
begin
    select * into v_job from public.print_jobs where id = p_job_id;
    if not found then
        return jsonb_build_object('ok', false, 'code', 'JOB_NOT_FOUND');
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('benfuwan:print-order:' || v_job.order_id, 0));
    perform 1 from public.print_jobs where order_id = v_job.order_id for update;
    select * into v_job from public.print_jobs where id = p_job_id;

    if v_safe_match and nullif(p_taskid, '') is not null and exists (
        select 1 from public.print_jobs
         where vendor_taskid = p_taskid and id <> p_job_id
    ) then
        v_safe_match := false;
        v_ambiguous := true;
    end if;

    v_quarantined := v_job.ambiguous_operation = 'prior_attempt_activity';
    if v_quarantined then
        update public.print_jobs
           set last_reconciled_at = v_now,
               reconcile_count = coalesce(reconcile_count, 0) + 1,
               vendor_raw_status = case when v_safe_match then coalesce(p_status, '') else vendor_raw_status end,
               vendor_raw_message = case when v_safe_match then left(coalesce(p_message, ''), 500) else vendor_raw_message end,
               started_at = case when v_safe_match and p_status = '1' then coalesce(started_at, v_now) else started_at end,
               completed_at = case when v_safe_match and p_status = '2' then coalesce(completed_at, v_now) else completed_at end,
               canceled_at = case when v_safe_match and p_status = '3' then coalesce(canceled_at, v_now) else canceled_at end
         where id = p_job_id
         returning * into v_job;
        return jsonb_build_object(
            'ok', true, 'code', 'RECONCILE_REQUIRED', 'job', to_jsonb(v_job),
            'found', v_safe_match, 'ambiguous', v_ambiguous,
            'quarantined', true);
    end if;

    if v_safe_match then
        v_next_state := case
            when p_status = '1' then 'PRINTING'
            when p_status = '2' then 'COMPLETED'
            when p_status = '3' then 'CANCELED'
            when p_status in ('4','5','6','7','8','11') then 'FAILED'
            else 'QUEUED'
        end;
        update public.print_jobs
           set vendor_taskid = nullif(p_taskid, ''),
               vendor_raw_status = coalesce(p_status, ''),
               vendor_raw_message = left(coalesce(p_message, ''), 500),
               state = v_next_state,
               ambiguous_operation = null,
               last_error = null,
               last_reconciled_at = v_now,
               reconcile_count = coalesce(reconcile_count, 0) + 1,
               started_at = case when p_status = '1' then coalesce(started_at, v_now) else started_at end,
               completed_at = case when p_status = '2' then coalesce(completed_at, v_now) else completed_at end,
               canceled_at = case when p_status = '3' then coalesce(canceled_at, v_now) else canceled_at end,
               updated_at = v_now
         where id = p_job_id
         returning * into v_job;
    elsif v_ambiguous then
        update public.print_jobs
           set state = 'UNKNOWN',
               ambiguous_operation = 'reconcile',
               last_error = '雲端查核找到多筆可能任務，無法安全判定；請人工確認',
               last_reconciled_at = v_now,
               reconcile_count = coalesce(reconcile_count, 0) + 1,
               updated_at = v_now
         where id = p_job_id
         returning * into v_job;
    elsif v_job.state not in ('COMPLETED', 'CANCELED', 'FAILED') then
        update public.print_jobs
           set state = 'UNKNOWN',
               last_error = '雲端未列印佇列找不到此任務；不可據此判定未建立或已完成',
               last_reconciled_at = v_now,
               reconcile_count = coalesce(reconcile_count, 0) + 1,
               updated_at = v_now
         where id = p_job_id
         returning * into v_job;
    else
        update public.print_jobs
           set last_reconciled_at = v_now,
               reconcile_count = coalesce(reconcile_count, 0) + 1
         where id = p_job_id
         returning * into v_job;
    end if;

    return jsonb_build_object(
        'ok', true,
        'code', case when v_ambiguous then 'RECONCILE_REQUIRED' else 'OK' end,
        'job', to_jsonb(v_job), 'found', v_safe_match,
        'ambiguous', v_ambiguous, 'quarantined', false);
end;
$$;

revoke all on function public.claim_print_send_if_safe(uuid,text,timestamptz,text)
    from public, anon, authenticated;
revoke all on function public.apply_print_callback_safely(uuid,text,text)
    from public, anon, authenticated;
revoke all on function public.apply_print_reconcile_safely(uuid,boolean,text,text,text,boolean)
    from public, anon, authenticated;
grant execute on function public.claim_print_send_if_safe(uuid,text,timestamptz,text)
    to service_role;
grant execute on function public.apply_print_callback_safely(uuid,text,text)
    to service_role;
grant execute on function public.apply_print_reconcile_safely(uuid,boolean,text,text,text,boolean)
    to service_role;
