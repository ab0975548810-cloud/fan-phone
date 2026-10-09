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

revoke all on function public.claim_print_send_if_safe(uuid,text,timestamptz,text)
    from public, anon, authenticated;
revoke all on function public.apply_print_callback_safely(uuid,text,text)
    from public, anon, authenticated;
grant execute on function public.claim_print_send_if_safe(uuid,text,timestamptz,text)
    to service_role;
grant execute on function public.apply_print_callback_safely(uuid,text,text)
    to service_role;
