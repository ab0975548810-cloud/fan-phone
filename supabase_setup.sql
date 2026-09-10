-- 本福丸訂製手機殼 v2：最小穩定持久化層
-- 前端不直接碰 Supabase；所有讀寫皆由 Flask 後端的 service-role key 執行。

create table if not exists public.app_store (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.orders (
  id text primary key,
  customer_name text not null,
  payment_method text not null,
  model_id text not null,
  model_name text not null,
  style_id text not null,
  style_name text not null,
  unit_price integer not null check (unit_price > 0),
  quantity integer not null default 1 check (quantity > 0),
  total integer not null check (total > 0),
  status text not null default '待處理',
  design_json jsonb,
  print_path text,
  mockup_path text,
  created_at_unix bigint not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_orders_created_at on public.orders(created_at desc);
create index if not exists idx_orders_status on public.orders(status);

alter table public.app_store enable row level security;
alter table public.orders enable row level security;

-- 後端使用 service-role，因此不需要對 anon/public 開 DB policy。
-- Public bucket：模板、貼紙、遮罩等可公開讀取。
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('case-assets', 'case-assets', true, 10485760, array['image/png','image/jpeg','image/webp'])
on conflict (id) do update set public = true, file_size_limit = 10485760, allowed_mime_types = array['image/png','image/jpeg','image/webp'];

-- Private bucket：客人預覽圖 / 生產圖。
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('case-private', 'case-private', false, 10485760, array['image/png','image/jpeg','image/webp'])
on conflict (id) do update set public = false, file_size_limit = 10485760, allowed_mime_types = array['image/png','image/jpeg','image/webp'];
