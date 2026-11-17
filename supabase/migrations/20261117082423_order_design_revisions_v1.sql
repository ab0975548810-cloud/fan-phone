-- Apply only after owner approval. No writes to orders, finance, stock or print tables.
create table public.order_design_versions (
  order_id text not null,
  version integer not null check(version > 0),
  document jsonb not null,
  actor text not null,
  request_id text not null,
  content_hash text not null,
  created_at timestamptz not null default now(),
  primary key(order_id, version),
  unique(order_id, request_id)
);
alter table public.order_design_versions enable row level security;
revoke all on public.order_design_versions from public, anon, authenticated, service_role;
grant select, insert on public.order_design_versions to service_role;

create function public.append_order_design_version(p_order text,p_expected integer,p_document jsonb,p_actor text,p_request text,p_hash text)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_current integer; v_previous public.order_design_versions;
begin
  if p_expected < 0 or p_order !~ '^[A-Za-z0-9-]{1,100}$' or jsonb_typeof(p_document) <> 'object' then
    raise exception 'invalid design revision';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('order-design:' || p_order,0));
  select * into v_previous from public.order_design_versions where order_id=p_order and request_id=p_request;
  if found then return jsonb_build_object('ok',v_previous.content_hash=p_hash,'version',v_previous.version); end if;
  select coalesce(max(version),0) into v_current from public.order_design_versions where order_id=p_order;
  if v_current <> p_expected then return jsonb_build_object('ok',false,'version',v_current); end if;
  insert into public.order_design_versions(order_id,version,document,actor,request_id,content_hash)
    values(p_order,v_current+1,p_document,p_actor,p_request,p_hash);
  return jsonb_build_object('ok',true,'version',v_current+1);
end $$;
revoke all on function public.append_order_design_version(text,integer,jsonb,text,text,text) from public,anon,authenticated;
grant execute on function public.append_order_design_version(text,integer,jsonb,text,text,text) to service_role;
