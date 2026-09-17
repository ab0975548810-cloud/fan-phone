-- Apply after supabase_setup.sql, with old application workers stopped.
-- SECURITY INVOKER + service-role-only execute: no public commerce API.
create or replace function public.commerce_commit(
    p_revision bigint, p_data jsonb, p_order jsonb default null, p_action text default ''
) returns boolean
language plpgsql security invoker set search_path = ''
as $$
declare
    previous jsonb;
    entry record;
    changed integer;
begin
    insert into public.app_store(key, value) values ('commerce_data', '{}'::jsonb)
    on conflict (key) do nothing;
    select value into previous from public.app_store where key = 'commerce_data' for update;
    if coalesce((previous->>'revision')::bigint, 0) <> p_revision then
        return false;
    end if;
    if (p_data->>'revision')::bigint is distinct from p_revision + 1 then
        raise exception 'Invalid commerce revision';
    end if;
    if jsonb_typeof(p_data->'inventory_ledger') is distinct from 'array'
       or jsonb_typeof(p_data->'requests') is distinct from 'object'
       or jsonb_typeof(p_data->'actions') is distinct from 'object' then
        raise exception 'Invalid commerce state';
    end if;
    -- Previously committed receipts and ledger rows are immutable.
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
revoke all on function public.commerce_commit(bigint,jsonb,jsonb,text) from public, anon, authenticated;
grant execute on function public.commerce_commit(bigint,jsonb,jsonb,text) to service_role;
grant select, insert, update on public.app_store to service_role;
grant select, insert, update, delete on public.orders to service_role;
