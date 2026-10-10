-- Cover common foreign-key joins and the application's recent-record filters.
create index if not exists sales_records_sold_at_idx on sales_records (sold_at desc);
create index if not exists sales_records_product_id_idx on sales_records (product_id);
create index if not exists customer_feedback_product_id_idx on customer_feedback (product_id);
create index if not exists customer_feedback_submitted_at_idx on customer_feedback (submitted_at desc);
create index if not exists agent_results_run_id_idx on agent_results (run_id);
create index if not exists recommendations_run_id_idx on recommendations (run_id);
create index if not exists approval_decisions_recommendation_id_idx on approval_decisions (recommendation_id);
create index if not exists audit_logs_run_id_idx on audit_logs (run_id);
create index if not exists audit_logs_created_at_idx on audit_logs (created_at desc);
create index if not exists inventory_movements_product_id_idx on inventory_movements (product_id);
create index if not exists promotions_product_id_idx on promotions (product_id);
