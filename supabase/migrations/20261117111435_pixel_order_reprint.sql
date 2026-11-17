-- No backfill and no alteration of existing tasks. Only service-role RPC access.
create function public.approve_pixel_reprint(p_order text,p_version integer,p_hash text,
    p_key text,p_actor text,p_reason text,p_cost integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
    d jsonb; s public.print_jobs%rowtype; j public.print_jobs%rowtype;
    prior public.print_requests%rowtype; result jsonb;
begin
    if p_version<2 or length(trim(p_reason)) not between 1 and 500 or p_cost<0 or p_cost>100000000 then
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
    result=public.authorize_manual_reprint(p_order,p_key,p_hash,p_actor,'',jsonb_build_object('artwork_token_nonce',gen_random_uuid()::text),false);
    if not coalesce((result->>'ok')::boolean,false) then return result; end if;
    update public.print_jobs set artwork_path=d->>'outputPath',artwork_sha256=d->>'outputSha',
        sku_id=s.sku_id,width_mm=s.width_mm,height_mm=s.height_mm,left_mm=s.left_mm,top_mm=s.top_mm,
        angle=s.angle,copies=s.copies,channel=s.channel,spot_color=s.spot_color
        where id=(result->'job'->>'id')::uuid returning * into j;
    update public.print_events set payload_json=jsonb_build_object('actor',p_actor,'version',p_version,'versionHash',p_hash,
        'reason',p_reason,'costCents',p_cost,'sourceJobId',s.id,'baseSha',d->>'baseSha','outputSha',d->>'outputSha','parameters',d->'profile'),
        raw_message='已比較 V1／V2，人工確認像素修補重印'
        where job_id=j.id and event_type='MANUAL_REPRINT_AUTHORIZED';
    return jsonb_build_object('ok',true,'job',to_jsonb(j));
end;
$$;
revoke all on function public.approve_pixel_reprint(text,integer,text,text,text,text,integer) from public,anon,authenticated;
grant execute on function public.approve_pixel_reprint(text,integer,text,text,text,text,integer) to service_role;
