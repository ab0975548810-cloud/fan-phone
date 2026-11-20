create table if not exists public.design_production_orders (
    id text primary key,
    order_id text not null,
    version integer not null check (version >= 2),
    content_hash text not null,
    actor text not null,
    created_at timestamptz not null default now(),
    unique (order_id, version),
    foreign key (order_id, version) references public.order_design_versions(order_id, version)
);
alter table public.design_production_orders enable row level security;
revoke all on public.design_production_orders from public, anon, authenticated, service_role;
grant select, insert on public.design_production_orders to service_role;
