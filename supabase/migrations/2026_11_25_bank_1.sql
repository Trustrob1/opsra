-- BANK-1 (25 Nov 2026): several bank accounts per business, each can be linked to a sales region; one is the default.
-- An invoice or quote can pick the account it shows; blank = the region's account, else the default.
-- Existing single account (bank_name / account_name / account_number) keeps working as the default until the list is saved.
alter table public.invoice_settings
  add column if not exists bank_accounts jsonb not null default '[]'::jsonb;
alter table public.invoices
  add column if not exists bank_account_id text;
alter table public.invoices
  drop constraint if exists invoices_bank_account_id_len;
alter table public.invoices
  add constraint invoices_bank_account_id_len check (bank_account_id is null or char_length(bank_account_id) <= 40);

-- check: should return 2
select count(*) as cols_should_be_2 from information_schema.columns
 where table_schema = 'public'
   and ((table_name = 'invoice_settings' and column_name = 'bank_accounts')
     or (table_name = 'invoices' and column_name = 'bank_account_id'));
