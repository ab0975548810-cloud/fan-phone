-- Cover the print_handoffs -> print_jobs foreign key used by cleanup and
-- referential checks. This is additive and does not modify production rows.
create index if not exists idx_print_handoffs_prepared_job_id
    on public.print_handoffs(prepared_job_id);
