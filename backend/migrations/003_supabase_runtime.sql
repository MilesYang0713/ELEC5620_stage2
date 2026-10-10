-- Runtime payloads keep complete results while normalized tables remain queryable.
alter table analysis_runs add column if not exists result jsonb not null default '{}'::jsonb;
alter table recommendations add column if not exists result jsonb not null default '{}'::jsonb;

-- Backend-only server key access. Never expose this role to browser code.
grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Illustrative daily sales for the demo products. Deterministic UUIDs make this
-- seed safe to rerun without duplicating the same sample rows.
with days as (
  select generate_series(0, 13) as day_offset
), product_set as (
  select unnest(array['P-001','P-002','P-003']) as product_id
), quantities as (
  select p.product_id, d.day_offset,
    case
      when p.product_id = 'P-001' and d.day_offset < 7 then 3
      when p.product_id = 'P-001' and d.day_offset = 7 then 10
      when p.product_id = 'P-001' then 4
      when p.product_id = 'P-002' and d.day_offset < 5 then 1
      when p.product_id = 'P-002' and d.day_offset < 7 then 0
      when p.product_id = 'P-002' and d.day_offset = 7 then 1
      when p.product_id = 'P-002' then 1
      when p.product_id = 'P-003' and d.day_offset < 6 then 4
      when p.product_id = 'P-003' and d.day_offset = 6 then 3
      when p.product_id = 'P-003' and d.day_offset < 12 then 2
      else 1
    end as quantity
  from product_set p cross join days d
)
insert into sales_records (id, product_id, sold_at, quantity, revenue)
select md5(product_id || ':' || (current_date - day_offset)::text)::uuid,
       product_id,
       ((current_date - day_offset)::timestamp + interval '12 hours') at time zone 'UTC',
       quantity,
       quantity * case product_id when 'P-001' then 18.50 when 'P-002' then 8.00 else 14.00 end
from quantities
on conflict (id) do nothing;
