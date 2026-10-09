-- Supabase/PostgreSQL target schema. Demo-mode API does not write to this schema yet.
create extension if not exists pgcrypto;

create table if not exists products (
  id text primary key, name text not null, category text not null,
  price numeric(10,2) not null check (price >= 0), created_at timestamptz not null default now()
);
create table if not exists sales_records (
  id uuid primary key default gen_random_uuid(), product_id text not null references products(id),
  sold_at timestamptz not null, quantity integer not null check (quantity >= 0), revenue numeric(10,2) not null
);
create table if not exists inventory_levels (
  product_id text primary key references products(id), quantity integer not null check (quantity >= 0), updated_at timestamptz not null default now()
);
create table if not exists inventory_movements (
  id uuid primary key default gen_random_uuid(), product_id text not null references products(id),
  movement_type text not null, quantity integer not null, occurred_at timestamptz not null default now(), note text
);
create table if not exists promotions (
  id uuid primary key default gen_random_uuid(), product_id text references products(id), title text not null,
  starts_at timestamptz not null, ends_at timestamptz not null, discount_percent numeric(5,2)
);
create table if not exists customer_feedback (
  id uuid primary key default gen_random_uuid(), product_id text references products(id), category text not null,
  content text not null, submitted_at timestamptz not null default now()
);
create table if not exists analysis_runs (
  id uuid primary key default gen_random_uuid(), question text not null, workflow text not null,
  status text not null, data_mode text not null, created_at timestamptz not null default now()
);
create table if not exists agent_results (
  id uuid primary key default gen_random_uuid(), run_id uuid not null references analysis_runs(id) on delete cascade,
  agent_name text not null, status text not null, result jsonb not null default '{}'::jsonb, created_at timestamptz not null default now()
);
create table if not exists recommendations (
  id uuid primary key default gen_random_uuid(), run_id uuid not null references analysis_runs(id) on delete cascade,
  title text not null, action text not null, priority text not null, high_risk boolean not null default false,
  status text not null, evidence jsonb not null default '[]'::jsonb, created_at timestamptz not null default now()
);
create table if not exists approval_decisions (
  id uuid primary key default gen_random_uuid(), recommendation_id uuid not null references recommendations(id),
  decision text not null check (decision in ('approved','rejected')), note text not null default '', decided_at timestamptz not null default now()
);
create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(), run_id uuid references analysis_runs(id), event text not null,
  details jsonb not null default '{}'::jsonb, created_at timestamptz not null default now()
);

-- Fail closed: browser roles cannot read or mutate operational/customer records.
-- Add narrowly scoped policies only after the intended authentication model is agreed.
alter table products enable row level security;
alter table sales_records enable row level security;
alter table inventory_levels enable row level security;
alter table inventory_movements enable row level security;
alter table promotions enable row level security;
alter table customer_feedback enable row level security;
alter table analysis_runs enable row level security;
alter table agent_results enable row level security;
alter table recommendations enable row level security;
alter table approval_decisions enable row level security;
alter table audit_logs enable row level security;
