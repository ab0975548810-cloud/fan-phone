-- Issue #87: transactional order -> print handoff outbox.
-- Apply only after a restorable snapshot and with old checkout workers stopped.
-- Rows created before this migration are REVIEW-only and are never auto-claimed.

create table if not exists public.print_handoff_control (
    singleton boolean primary key default true check (singleton),
    release_cutoff timestamptz not null
);

insert into public.print_handoff_control(singleton, release_cutoff)
values (true, transaction_timestamp())
on conflict (singleton) do nothing;

create table if not exists public.print_handoffs (
    id uuid primary key default gen_random_uuid(),
    order_id text not null unique references public.orders(id) on delete cascade,
    request_key text not null unique,
    marker_version text not null,
    state text not null check (state in (
        'PENDING','CLAIMED','RETRY','PREPARED','REVIEW','FAILED'
    )),
    attempt_count integer not null default 0 check (attempt_count >= 0),
    next_attempt_at timestamptz,
    lease_token uuid,
    lease_expires_at timestamptz,
    prepared_job_id uuid references public.print_jobs(id) on delete restrict,
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (state <> 'PREPARED' or prepared_job_id is not null)
);

create index if not exists idx_print_handoffs_due
    on public.print_handoffs(state, next_attempt_at, created_at);
create index if not exists idx_print_handoffs_lease
    on public.print_handoffs(state, lease_expires_at);

alter table public.print_handoff_control enable row level security;
alter table public.print_handoffs enable row level security;
revoke all on table public.print_handoff_control from public, anon, authenticated;
revoke all on table public.print_handoffs from public, anon, authenticated;
grant select on table public.print_handoff_control to service_role;
grant select, insert, update on table public.print_handoffs to service_role;

-- One-time release boundary. Old Phase 3.3 receipts are visible for review but
-- are intentionally ineligible for worker claims, even after a redeploy.
insert into public.print_handoffs(
    order_id, request_key, marker_version, state, next_attempt_at,
    last_error_code, last_error_at, created_at, updated_at
)
select
    receipt.value->'response'->>'order_id', receipt.key,
    'legacy-auto-print-v1', 'REVIEW', null,
    'LEGACY_CUTOFF_REVIEW', now(), now(), now()
from public.app_store store
cross join lateral jsonb_each(coalesce(store.value->'requests', '{}'::jsonb)) receipt
join public.orders order_row
  on order_row.id = receipt.value->'response'->>'order_id'
where store.key = 'commerce_data'
  and receipt.value->'auto_print_v1' = 'true'::jsonb
  and not (receipt.value ? 'auto_print_handoff_v1')
  and not exists (
      select 1 from public.print_jobs job
      where job.order_id = receipt.value->'response'->>'order_id'
  )
on conflict (order_id) do nothing;

create or replace function public.claim_print_handoffs(
    p_limit integer default 20, p_lease_seconds integer default 60
) returns setof public.print_handoffs
language plpgsql security invoker set search_path = ''
as $$
begin
    if p_limit < 1 or p_limit > 50 or p_lease_seconds < 15 or p_lease_seconds > 600 then
        raise exception 'Invalid print handoff claim bounds';
    end if;
    return query
    with candidates as (
        select handoff.id
        from public.print_handoffs handoff
        cross join public.print_handoff_control control
        where handoff.marker_version = 'auto-print-handoff-v1'
          and handoff.created_at >= control.release_cutoff
          and (
              (handoff.state in ('PENDING','RETRY')
               and coalesce(handoff.next_attempt_at, '-infinity'::timestamptz) <= now())
              or (handoff.state = 'CLAIMED' and handoff.lease_expires_at <= now())
          )
        order by handoff.created_at, handoff.id
        for update of handoff skip locked
        limit p_limit
    )
    update public.print_handoffs handoff
       set state = 'CLAIMED',
           attempt_count = handoff.attempt_count + 1,
           lease_token = gen_random_uuid(),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
      from candidates
     where handoff.id = candidates.id
    returning handoff.*;
end;
$$;

create or replace function public.finish_print_handoff(
    p_id uuid, p_lease_token uuid, p_state text,
    p_prepared_job_id uuid default null, p_error_code text default null,
    p_retry_seconds integer default null
) returns jsonb
language plpgsql security invoker set search_path = ''
as $$
declare
    changed public.print_handoffs;
    current_handoff public.print_handoffs;
begin
    if p_state not in ('RETRY','PREPARED','REVIEW','FAILED') then
        raise exception 'Invalid print handoff finish state';
    end if;
    if p_state = 'RETRY' and (p_retry_seconds is null or p_retry_seconds < 1 or p_retry_seconds > 3600) then
        raise exception 'Invalid print handoff retry delay';
    end if;
    select * into current_handoff
      from public.print_handoffs
     where id = p_id and state = 'CLAIMED' and lease_token = p_lease_token
     for update;
    if current_handoff.id is null then
        return jsonb_build_object('ok', false, 'code', 'LEASE_LOST');
    end if;
    if p_state = 'PREPARED' then
        if p_prepared_job_id is null then
            return jsonb_build_object('ok', false, 'code', 'PREPARED_JOB_REQUIRED');
        end if;
        if not exists (
            select 1 from public.print_jobs job
             where job.id = p_prepared_job_id
               and job.order_id = current_handoff.order_id
        ) then
            return jsonb_build_object('ok', false, 'code', 'PREPARED_JOB_MISMATCH');
        end if;
    end if;
    update public.print_handoffs
       set state = p_state,
           prepared_job_id = case when p_state = 'PREPARED' then p_prepared_job_id else prepared_job_id end,
           last_error_code = left(coalesce(p_error_code, ''), 100),
           last_error_at = case when p_error_code is null then last_error_at else now() end,
           next_attempt_at = case when p_state = 'RETRY'
                                  then now() + make_interval(secs => p_retry_seconds)
                                  else null end,
           lease_token = null,
           lease_expires_at = null,
           updated_at = now()
     where id = current_handoff.id and state = 'CLAIMED' and lease_token = p_lease_token
    returning * into changed;
    if changed.id is null then
        return jsonb_build_object('ok', false, 'code', 'LEASE_LOST');
    end if;
    return jsonb_build_object('ok', true, 'state', changed.state,
                              'attempt_count', changed.attempt_count);
end;
$$;

revoke all on function public.claim_print_handoffs(integer,integer)
    from public, anon, authenticated;
revoke all on function public.finish_print_handoff(uuid,uuid,text,uuid,text,integer)
    from public, anon, authenticated;
grant execute on function public.claim_print_handoffs(integer,integer) to service_role;
grant execute on function public.finish_print_handoff(uuid,uuid,text,uuid,text,integer) to service_role;

-- Preserve the Phase 2 append-only/CAS guards while atomically creating the
-- outbox row for the exact checkout receipt and response.
create or replace function public.commerce_commit(
    p_revision bigint, p_data jsonb, p_order jsonb default null, p_action text default ''
) returns boolean
language plpgsql security invoker set search_path = ''
as $$
declare
    previous jsonb;
    entry record;
    changed integer;
    handoff jsonb;
    receipt jsonb;
    cutoff timestamptz;
begin
    insert into public.app_store(key, value) values ('commerce_data', '{}'::jsonb)
    on conflict (key) do nothing;
    select value into previous from public.app_store where key = 'commerce_data' for update;
    if coalesce((previous->>'revision')::bigint, 0) <> p_revision then return false; end if;
    if (p_data->>'revision')::bigint is distinct from p_revision + 1 then
        raise exception 'Invalid commerce revision';
    end if;
    if jsonb_typeof(p_data->'inventory_ledger') is distinct from 'array'
       or jsonb_typeof(p_data->'requests') is distinct from 'object'
       or jsonb_typeof(p_data->'actions') is distinct from 'object' then
        raise exception 'Invalid commerce state';
    end if;
    if coalesce((p_data->>'version')::int, 0) < 3
       or jsonb_typeof(p_data->'expenses') is distinct from 'object'
       or jsonb_typeof(p_data->'expense_ledger') is distinct from 'array' then
        raise exception 'Phase 2 writer required';
    end if;
    for entry in select value, ordinality from jsonb_array_elements(coalesce(previous->'expense_ledger', '[]'::jsonb)) with ordinality loop
        if p_data->'expense_ledger'->(entry.ordinality::integer - 1) is distinct from entry.value then
            raise exception 'Expense ledger is append-only';
        end if;
    end loop;
    if not (p_data->'requests' @> coalesce(previous->'requests', '{}'::jsonb))
       or not (p_data->'actions' @> coalesce(previous->'actions', '{}'::jsonb)) then
        raise exception 'Cannot rewrite idempotency receipts';
    end if;
    for entry in select value, ordinality from jsonb_array_elements(coalesce(previous->'inventory_ledger', '[]'::jsonb)) with ordinality loop
        if p_data->'inventory_ledger'->(entry.ordinality::integer - 1) is distinct from entry.value then
            raise exception 'Inventory ledger is append-only';
        end if;
    end loop;
    for entry in select key, value from jsonb_each(coalesce(previous->'order_finance', '{}'::jsonb)) loop
        if ((p_data->'order_finance'->entry.key) - array['status','inventory_quantity','inventory_reserved','inventory_sequence'])
           is distinct from (entry.value - array['status','inventory_quantity','inventory_reserved','inventory_sequence']) then
            raise exception 'Order financial snapshots are immutable';
        end if;
    end loop;
    if p_action = 'create' then
        insert into public.orders(id,customer_name,payment_method,model_id,model_name,style_id,style_name,
            unit_price,quantity,total,status,design_json,print_path,mockup_path,created_at_unix)
        values (p_order->>'id',p_order->>'customer_name',p_order->>'payment_method',p_order->>'model_id',
            p_order->>'model_name',p_order->>'style_id',p_order->>'style_name',(p_order->>'unit_price')::integer,
            (p_order->>'quantity')::integer,(p_order->>'total')::integer,p_order->>'status',p_order->'design_json',
            p_order->>'print_path',p_order->>'mockup_path',(p_order->>'created_at_unix')::bigint);
        handoff := p_order->'_print_handoff';
        if handoff is not null then
            receipt := p_data->'requests'->(handoff->>'request_key');
            select release_cutoff into cutoff from public.print_handoff_control where singleton = true;
            if handoff->>'version' is distinct from 'auto-print-handoff-v1'
               or handoff->>'order_id' is distinct from p_order->>'id'
               or receipt->'auto_print_v1' is distinct from 'true'::jsonb
               or receipt->'auto_print_handoff_v1'->>'version' is distinct from 'auto-print-handoff-v1'
               or receipt->'auto_print_handoff_v1'->>'order_id' is distinct from p_order->>'id'
               or receipt->'response'->>'order_id' is distinct from p_order->>'id'
               or transaction_timestamp() < cutoff then
                raise exception 'Invalid print handoff marker';
            end if;
            insert into public.print_handoffs(
                order_id, request_key, marker_version, state, next_attempt_at
            ) values (
                p_order->>'id', handoff->>'request_key',
                'auto-print-handoff-v1', 'PENDING', now()
            );
        end if;
    elsif p_action = 'status' then
        update public.orders set status = p_order->>'status' where id = p_order->>'id';
        get diagnostics changed = row_count;
        if changed <> 1 then raise exception 'Order missing'; end if;
    elsif p_action = 'delete' then
        delete from public.orders where id = p_order->>'id' and status = '作廢';
        get diagnostics changed = row_count;
        if changed <> 1 then raise exception 'Order missing or not void'; end if;
    elsif p_action <> '' then
        raise exception 'Unknown commerce action';
    end if;
    update public.app_store set value = p_data, updated_at = now() where key = 'commerce_data';
    return true;
end;
$$;

revoke all on function public.commerce_commit(bigint,jsonb,jsonb,text)
    from public, anon, authenticated;
grant execute on function public.commerce_commit(bigint,jsonb,jsonb,text) to service_role;
