-- RowRunner print worker — atomic claim RPCs on the shared `orders` table.
--
-- Run once in Supabase: Dashboard ▸ SQL Editor ▸ New query ▸ paste ▸ Run.
-- Idempotent (create or replace) and safe to run on top of the existing schema.
--
-- ⚠ Confirm the project ref in the URL is  kboevpucqjoftgmhrkzq  before running —
--    there are other projects in this account.
--    https://supabase.com/dashboard/project/kboevpucqjoftgmhrkzq/sql/new
--
-- These give the print worker exactly-once printing WITHOUT the service_role key:
-- both are SECURITY DEFINER, so the public anon role may call them, but they only
-- ever touch printed_at (never `code`, never anything else).

-- mark_printed(id): atomically claim a row for printing.
-- Sets printed_at = now() only if it is still null, and returns TRUE iff THIS call
-- won the row. Two workers racing → exactly one gets TRUE.
create or replace function public.mark_printed(p_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  n int;
begin
  update public.orders
     set printed_at = now()
   where id = p_id
     and printed_at is null;
  get diagnostics n = row_count;
  return n > 0;
end
$$;

-- mark_unprinted(id): release a claimed row after a print hardware failure so the
-- worker retries it on the next poll.
create or replace function public.mark_unprinted(p_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.orders
     set printed_at = null
   where id = p_id;
end
$$;

grant execute on function public.mark_printed(uuid)   to anon, authenticated;
grant execute on function public.mark_unprinted(uuid) to anon, authenticated;
