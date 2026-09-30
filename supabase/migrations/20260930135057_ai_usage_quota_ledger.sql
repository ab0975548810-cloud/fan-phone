-- Persistent RunPod usage ledger. Apply only through the normal reviewed
-- Supabase migration process; the storefront never receives table access.

create table if not exists public.ai_usage_events (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null unique,
    client_hash text not null check (client_hash ~ '^[0-9a-f]{64}$'),
    ip_hash text not null check (ip_hash ~ '^[0-9a-f]{64}$'),
    state text not null check (state in (
        'RESERVED','SUBMITTED','COMPLETED','FAILED','RELEASED'
    )),
    counted boolean not null default false,
    runpod_job_id text,
    created_at timestamptz not null default now(),
    submitted_at timestamptz,
    finished_at timestamptz
);

create index if not exists idx_ai_usage_client_submitted
    on public.ai_usage_events(client_hash, submitted_at desc);
create index if not exists idx_ai_usage_ip_submitted
    on public.ai_usage_events(ip_hash, submitted_at desc);
create index if not exists idx_ai_usage_submitted
    on public.ai_usage_events(submitted_at desc);
create index if not exists idx_ai_usage_state_created
    on public.ai_usage_events(state, created_at);

alter table public.ai_usage_events enable row level security;
revoke all on table public.ai_usage_events from public, anon, authenticated;
grant select, insert, update on table public.ai_usage_events to service_role;

create or replace function public.reserve_ai_usage(
    p_request_id uuid,
    p_client_hash text,
    p_ip_hash text
) returns jsonb
language plpgsql security invoker set search_path = ''
as $$
declare
    v_now timestamptz := clock_timestamp();
    v_client_used bigint;
    v_ip_used bigint;
    v_global_used bigint;
    v_active bigint;
    v_existing public.ai_usage_events%rowtype;
begin
    if p_request_id is null
       or p_client_hash !~ '^[0-9a-f]{64}$'
       or p_ip_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid AI quota reservation identity';
    end if;

    -- Serialize every quota decision. Counts and reservation insertion remain in
    -- one transaction, so concurrent app instances cannot pass the same limit.
    perform pg_advisory_xact_lock(hashtextextended('benfuwan:runpod-ai-quota:v1', 0));

    -- A worker can disappear after reserving and before receiving a RunPod id.
    update public.ai_usage_events
       set state = 'RELEASED', counted = false, finished_at = v_now
     where state = 'RESERVED'
       and created_at < v_now - interval '10 minutes';

    -- RunPod calls are bounded to 180 seconds. This recovery prevents an abrupt
    -- process death from occupying an active slot forever; the event stays
    -- counted because a provider job id had already been obtained.
    update public.ai_usage_events
       set state = 'FAILED', finished_at = v_now
     where state = 'SUBMITTED'
       and submitted_at < v_now - interval '10 minutes';

    select * into v_existing
      from public.ai_usage_events
     where request_id = p_request_id;
    if found then
        if v_existing.client_hash is distinct from p_client_hash
           or v_existing.ip_hash is distinct from p_ip_hash then
            raise exception 'AI quota request identity mismatch';
        end if;
        return jsonb_build_object(
            'reserved', v_existing.state in ('RESERVED','SUBMITTED'),
            'code', case when v_existing.state in ('RESERVED','SUBMITTED') then 'OK' else 'REQUEST_CLOSED' end
        );
    end if;

    select count(*) into v_client_used
      from public.ai_usage_events
     where client_hash = p_client_hash
       and counted = true
       and submitted_at >= v_now - interval '24 hours';
    if v_client_used >= 5 then
        return jsonb_build_object('reserved', false, 'code', 'AI_DEVICE_DAILY_LIMIT');
    end if;

    select count(*) into v_ip_used
      from public.ai_usage_events
     where ip_hash = p_ip_hash
       and counted = true
       and submitted_at >= v_now - interval '24 hours';
    if v_ip_used >= 15 then
        return jsonb_build_object('reserved', false, 'code', 'AI_IP_DAILY_LIMIT');
    end if;

    select count(*) into v_global_used
      from public.ai_usage_events
     where counted = true
       and submitted_at >= v_now - interval '24 hours';
    if v_global_used >= 60 then
        return jsonb_build_object('reserved', false, 'code', 'AI_GLOBAL_DAILY_LIMIT');
    end if;

    select count(*) into v_active
      from public.ai_usage_events
     where state in ('RESERVED','SUBMITTED');
    if v_active >= 2 then
        return jsonb_build_object('reserved', false, 'code', 'AI_BUSY');
    end if;

    insert into public.ai_usage_events(request_id, client_hash, ip_hash, state, counted)
    values (p_request_id, p_client_hash, p_ip_hash, 'RESERVED', false);

    return jsonb_build_object(
        'reserved', true,
        'code', 'OK',
        'global_used_24h', v_global_used,
        'active_now', v_active + 1
    );
end;
$$;

create or replace function public.mark_ai_usage_submitted(
    p_request_id uuid,
    p_runpod_job_id text
) returns boolean
language plpgsql security invoker set search_path = ''
as $$
declare
    v_changed integer;
begin
    if nullif(btrim(p_runpod_job_id), '') is null then
        raise exception 'RunPod job id is required';
    end if;
    update public.ai_usage_events
       set state = 'SUBMITTED',
           counted = true,
           runpod_job_id = p_runpod_job_id,
           submitted_at = clock_timestamp()
     where request_id = p_request_id
       and state = 'RESERVED'
       and counted = false;
    get diagnostics v_changed = row_count;
    if v_changed = 1 then return true; end if;
    return exists (
        select 1 from public.ai_usage_events
         where request_id = p_request_id
           and state = 'SUBMITTED'
           and counted = true
           and runpod_job_id = p_runpod_job_id
    );
end;
$$;

create or replace function public.release_ai_usage(
    p_request_id uuid
) returns boolean
language plpgsql security invoker set search_path = ''
as $$
declare
    v_changed integer;
begin
    update public.ai_usage_events
       set state = 'RELEASED', counted = false, finished_at = clock_timestamp()
     where request_id = p_request_id
       and state = 'RESERVED'
       and counted = false;
    get diagnostics v_changed = row_count;
    if v_changed = 1 then return true; end if;
    return exists (
        select 1 from public.ai_usage_events
         where request_id = p_request_id
           and state = 'RELEASED'
           and counted = false
    );
end;
$$;

create or replace function public.finish_ai_usage(
    p_request_id uuid,
    p_state text
) returns boolean
language plpgsql security invoker set search_path = ''
as $$
declare
    v_changed integer;
begin
    if p_state not in ('COMPLETED','FAILED') then
        raise exception 'Invalid final AI usage state';
    end if;
    update public.ai_usage_events
       set state = p_state, finished_at = clock_timestamp()
     where request_id = p_request_id
       and state = 'SUBMITTED'
       and counted = true;
    get diagnostics v_changed = row_count;
    if v_changed = 1 then return true; end if;
    return exists (
        select 1 from public.ai_usage_events
         where request_id = p_request_id
           and state = p_state
           and counted = true
    );
end;
$$;

create or replace function public.get_ai_usage_diagnostics()
returns jsonb
language plpgsql security invoker set search_path = ''
as $$
declare
    v_now timestamptz := clock_timestamp();
    v_global_used bigint;
    v_active bigint;
begin
    perform pg_advisory_xact_lock(hashtextextended('benfuwan:runpod-ai-quota:v1', 0));
    update public.ai_usage_events
       set state = 'RELEASED', counted = false, finished_at = v_now
     where state = 'RESERVED'
       and created_at < v_now - interval '10 minutes';
    update public.ai_usage_events
       set state = 'FAILED', finished_at = v_now
     where state = 'SUBMITTED'
       and submitted_at < v_now - interval '10 minutes';
    select count(*) into v_global_used
      from public.ai_usage_events
     where counted = true
       and submitted_at >= v_now - interval '24 hours';
    select count(*) into v_active
      from public.ai_usage_events
     where state in ('RESERVED','SUBMITTED');
    return jsonb_build_object('global_used_24h', v_global_used, 'active_now', v_active);
end;
$$;

revoke all on function public.reserve_ai_usage(uuid,text,text) from public, anon, authenticated;
revoke all on function public.mark_ai_usage_submitted(uuid,text) from public, anon, authenticated;
revoke all on function public.release_ai_usage(uuid) from public, anon, authenticated;
revoke all on function public.finish_ai_usage(uuid,text) from public, anon, authenticated;
revoke all on function public.get_ai_usage_diagnostics() from public, anon, authenticated;

grant execute on function public.reserve_ai_usage(uuid,text,text) to service_role;
grant execute on function public.mark_ai_usage_submitted(uuid,text) to service_role;
grant execute on function public.release_ai_usage(uuid) to service_role;
grant execute on function public.finish_ai_usage(uuid,text) to service_role;
grant execute on function public.get_ai_usage_diagnostics() to service_role;
