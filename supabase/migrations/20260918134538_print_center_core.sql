-- Print Phase 3.0. Apply only after a restorable database snapshot.
-- Vendor credentials are environment-only and must never be stored here.

create table if not exists public.production_profiles (
    sku_id text primary key,
    width_mm numeric(9,3) not null check (width_mm > 0),
    height_mm numeric(9,3) not null check (height_mm > 0),
    left_mm numeric(9,3) not null default 0,
    top_mm numeric(9,3) not null default 0,
    copies integer not null default 1 check (copies between 1 and 99),
    spot_color text not null default '',
    channel text not null,
    angle numeric(9,3) not null default 0,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.print_jobs (
    id uuid primary key,
    order_id text not null,
    attempt_no integer not null check (attempt_no > 0),
    sku_id text,
    vendor_taskid text,
    artwork_path text not null,
    artwork_sha256 text,
    artwork_token_nonce text not null,
    artwork_token_expires_at timestamptz,
    profile_complete boolean not null default false,
    width_mm numeric(9,3),
    height_mm numeric(9,3),
    left_mm numeric(9,3),
    top_mm numeric(9,3),
    copies integer,
    spot_color text,
    channel text,
    angle numeric(9,3),
    device_id text,
    state text not null check (state in (
        'PREPARED','SENDING','QUEUED','STARTING','PRINTING',
        'CANCELING','COMPLETED','CANCELED','FAILED','UNKNOWN'
    )),
    vendor_raw_status text,
    vendor_raw_message text,
    ambiguous_operation text,
    last_error text,
    reconcile_count integer not null default 0,
    last_reconciled_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    prepared_at timestamptz not null default now(),
    sent_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    canceled_at timestamptz,
    unique (order_id, attempt_no)
);

create unique index if not exists idx_print_jobs_vendor_taskid
    on public.print_jobs(vendor_taskid) where vendor_taskid is not null;
create unique index if not exists idx_print_jobs_one_active_order
    on public.print_jobs(order_id)
    where state in ('PREPARED','SENDING','QUEUED','STARTING','PRINTING','CANCELING','UNKNOWN');
create index if not exists idx_print_jobs_updated_at on public.print_jobs(updated_at desc);
create index if not exists idx_print_jobs_state_updated on public.print_jobs(state, updated_at desc);

create table if not exists public.print_requests (
    request_key text primary key,
    operation text not null check (operation in ('prepare','send','start','cancel','reconcile','profile_snapshot')),
    job_id uuid references public.print_jobs(id) on delete restrict,
    request_hash text not null,
    status text not null check (status in ('IN_PROGRESS','COMPLETED','UNKNOWN','FAILED')),
    response_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_print_requests_job on public.print_requests(job_id, created_at desc);

create table if not exists public.print_events (
    id uuid primary key,
    job_id uuid not null references public.print_jobs(id) on delete restrict,
    event_key text not null unique,
    event_type text not null,
    raw_status text,
    raw_message text,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_print_events_job_created on public.print_events(job_id, created_at desc);

create table if not exists public.printer_status_events (
    id uuid primary key,
    event_key text not null unique,
    device_id text not null,
    raw_status text,
    raw_message text,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_printer_status_device_created
    on public.printer_status_events(device_id, created_at desc);

alter table public.production_profiles enable row level security;
alter table public.print_jobs enable row level security;
alter table public.print_requests enable row level security;
alter table public.print_events enable row level security;
alter table public.printer_status_events enable row level security;

revoke all on table public.production_profiles from public, anon, authenticated;
revoke all on table public.print_jobs from public, anon, authenticated;
revoke all on table public.print_requests from public, anon, authenticated;
revoke all on table public.print_events from public, anon, authenticated;
revoke all on table public.printer_status_events from public, anon, authenticated;

grant select, insert, update, delete on table public.production_profiles to service_role;
grant select, insert, update on table public.print_jobs to service_role;
grant select, insert, update on table public.print_requests to service_role;
grant select, insert on table public.print_events to service_role;
grant select, insert on table public.printer_status_events to service_role;
