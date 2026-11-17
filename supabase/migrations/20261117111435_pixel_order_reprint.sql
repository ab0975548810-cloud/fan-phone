-- No backfill and no alteration of existing tasks. Only service-role RPC access.
create function public.approve_pixel_reprint(p_order text,p_version integer,p_hash text,
    p_key text,p_actor text,p_reason text,p_cost integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
    d jsonb; s public.print_jobs%rowtype; j public.print_jobs%rowtype;
    prior public.print_requests%rowtype; result jsonb;
begin
    if p_version is null or p_version<2 or p_reason is null or length(trim(p_reason)) not between 1 and 500 or p_cost is null or p_cost<0 or p_cost>100000000
       or nullif(p_actor,'') is null or p_key is null or p_key !~ '^[A-Za-z0-9_-]{16,100}$' then
        return jsonb_build_object('ok',false); end if;
    perform pg_advisory_xact_lock(hashtextextended('benfuwan:print-order:'||p_order,0));
    -- Same lock used by append_order_design_version prevents approval racing a save.
    perform pg_advisory_xact_lock(hashtextextended('order-design:'||p_order,0));
    select * into prior from public.print_requests where request_key=p_key;
    if found then
        select * into j from public.print_jobs where id=prior.job_id;
        return jsonb_build_object('ok',prior.request_hash=p_hash,'job',to_jsonb(j));
    end if;
    select document into d from public.order_design_versions where order_id=p_order and version=p_version and content_hash=p_hash;
    if d is null or d->>'mode'<>'pixel-v1' or p_version<>(select max(version) from public.order_design_versions where order_id=p_order)
       or exists(select 1 from public.print_jobs where order_id=p_order and
          (state in ('PREPARED','SENDING','QUEUED','STARTING','PRINTING','CANCELING','UNKNOWN') or ambiguous_operation is not null)) then
        return jsonb_build_object('ok',false); end if;
    select * into s from public.print_jobs where order_id=p_order and id=(d->'profile'->>'sourceJobId')::uuid;
    if s.id is null or s.artwork_sha256<>d->>'baseSha' or not s.profile_complete
       or jsonb_build_object('sourceJobId',s.id,'sku_id',s.sku_id,'width_mm',s.width_mm,'height_mm',s.height_mm,
          'left_mm',s.left_mm,'top_mm',s.top_mm,'angle',s.angle,'copies',s.copies,'channel',s.channel,'spot_color',s.spot_color)<>d->'profile' then
        return jsonb_build_object('ok',false); end if;
    insert into public.print_jobs(id,order_id,attempt_no,manual_independent,sku_id,artwork_path,artwork_sha256,
        artwork_token_nonce,profile_complete,width_mm,height_mm,left_mm,top_mm,angle,copies,channel,spot_color,state)
    values(gen_random_uuid(),p_order,(select coalesce(max(attempt_no),0)+1 from public.print_jobs where order_id=p_order),
        true,s.sku_id,d->>'outputPath',d->>'outputSha',gen_random_uuid()::text,true,
        s.width_mm,s.height_mm,s.left_mm,s.top_mm,s.angle,s.copies,s.channel,s.spot_color,'PREPARED') returning * into j;
    insert into public.print_events(id,job_id,event_key,event_type,raw_message,payload_json)
    values(gen_random_uuid(),j.id,p_key,'MANUAL_REPRINT_AUTHORIZED','已比較 V1／V2，人工確認像素修補重印',
        jsonb_build_object('actor',p_actor,'version',p_version,'versionHash',p_hash,
        'reason',p_reason,'costCents',p_cost,'sourceJobId',s.id,'baseSha',d->>'baseSha','outputSha',d->>'outputSha','parameters',d->'profile'));
    insert into public.print_requests(request_key,operation,job_id,request_hash,status,response_json)
    values(p_key,'manual_reprint',j.id,p_hash,'COMPLETED',jsonb_build_object('job_id',j.id));
    return jsonb_build_object('ok',true,'job',to_jsonb(j));
end;
$$;
revoke all on function public.approve_pixel_reprint(text,integer,text,text,text,text,integer) from public,anon,authenticated;
grant execute on function public.approve_pixel_reprint(text,integer,text,text,text,text,integer) to service_role;

-- Narrow guard: only NEW pixel-approved jobs. Existing tasks are unaffected.
-- The DB boundary also closes the race with the existing profile snapshot API.
create function public.guard_pixel_reprint_geometry()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
    if row(new.sku_id,new.width_mm,new.height_mm,new.left_mm,new.top_mm,new.angle,
           new.copies,new.channel,new.spot_color,new.artwork_path,new.artwork_sha256,new.manual_independent)
       is distinct from
       row(old.sku_id,old.width_mm,old.height_mm,old.left_mm,old.top_mm,old.angle,
           old.copies,old.channel,old.spot_color,old.artwork_path,old.artwork_sha256,old.manual_independent)
       and exists(select 1 from public.print_events where job_id=old.id
           and event_type='MANUAL_REPRINT_AUTHORIZED' and payload_json->>'versionHash' is not null) then
        raise exception 'Approved pixel reprint geometry is immutable' using errcode='23514';
    end if;
    return new;
end;
$$;
revoke all on function public.guard_pixel_reprint_geometry() from public,anon,authenticated;
grant execute on function public.guard_pixel_reprint_geometry() to service_role;
create trigger pixel_reprint_geometry_immutable before update on public.print_jobs
for each row execute function public.guard_pixel_reprint_geometry();
