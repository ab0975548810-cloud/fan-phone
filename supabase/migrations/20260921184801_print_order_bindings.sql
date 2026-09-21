-- Print Phase 3.1.1. Apply only after a restorable database snapshot.
-- This table is print-only and must never be joined into commerce accounting.

create table if not exists public.print_order_bindings (
    order_id text primary key references public.orders(id) on delete cascade,
    sku_id text not null,
    source text not null default 'ADMIN_CONFIRMED'
        check (source in ('ADMIN_CONFIRMED')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.print_order_bindings enable row level security;

revoke all on table public.print_order_bindings from public, anon, authenticated;
grant select, insert, update on table public.print_order_bindings to service_role;
