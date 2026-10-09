insert into products (id, name, category, price) values
('P-001','Harbour Blend Coffee','Pantry',18.50),
('P-002','Coastal Oat Biscuits','Pantry',8.00),
('P-003','Wattle Hand Balm','Wellness',14.00)
on conflict (id) do nothing;

insert into inventory_levels (product_id, quantity) values ('P-001',12),('P-002',86),('P-003',9)
on conflict (product_id) do nothing;

insert into customer_feedback (product_id, category, content, submitted_at) values
('P-001','product','Love the flavour, but it was out of stock twice this month.',now()-interval '2 days'),
('P-002','product','The pack size feels small for the price.',now()-interval '5 days');
