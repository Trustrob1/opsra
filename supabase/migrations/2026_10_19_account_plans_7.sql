-- ACCOUNT-PLANS AP-7: extra users (seats) are bought through the same order table.
-- Run once in the Supabase SQL editor.
ALTER TABLE org_plan_orders DROP CONSTRAINT IF EXISTS org_plan_orders_change_kind_check;
ALTER TABLE org_plan_orders ADD CONSTRAINT org_plan_orders_change_kind_check
  CHECK (change_kind IN ('new','renewal','upgrade','switch','downgrade_renewal','seats'));
