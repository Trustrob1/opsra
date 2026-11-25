-- INV-1: quotations, invoices and receipts (backend core). Safe to run more than once. Additive only.
-- Tables checked absent in Supabase on 25 Nov 2026: invoice_settings, invoices, invoice_items, receipts, invoice_counters.

-- One row per business: what prints on its quotes, invoices and receipts.
CREATE TABLE IF NOT EXISTS invoice_settings (
  org_id uuid PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
  business_name text,
  address text,
  phone text,
  email text,
  rc_number text,
  tin text,
  logo_url text,
  bank_name text,
  account_name text,
  account_number text,
  quote_prefix text NOT NULL DEFAULT 'QT-',
  invoice_prefix text NOT NULL DEFAULT 'INV-',
  receipt_prefix text NOT NULL DEFAULT 'RCT-',
  vat_enabled boolean NOT NULL DEFAULT false,
  vat_rate numeric(5,2) NOT NULL DEFAULT 7.5 CHECK (vat_rate >= 0 AND vat_rate <= 100),
  default_due_days integer NOT NULL DEFAULT 7 CHECK (default_due_days BETWEEN 0 AND 365),
  default_quote_valid_days integer NOT NULL DEFAULT 14 CHECK (default_quote_valid_days BETWEEN 1 AND 365),
  default_terms text,
  footer text,
  brand_colour text NOT NULL DEFAULT '#0d9488',
  email_reply_to text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Quotes and invoices share one table (doc_type). number is NULL while a draft; given out at issue.
CREATE TABLE IF NOT EXISTS invoices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  doc_type text NOT NULL CHECK (doc_type IN ('quote','invoice')),
  number text,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','issued','accepted','declined','part_paid','paid','void')),
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
  customer_name text,
  customer_phone text,
  customer_email text,
  customer_address text,
  currency text NOT NULL DEFAULT 'NGN',
  subtotal numeric(14,2) NOT NULL DEFAULT 0,
  discount numeric(14,2) NOT NULL DEFAULT 0 CHECK (discount >= 0),
  vat_rate numeric(5,2) NOT NULL DEFAULT 0,
  vat_amount numeric(14,2) NOT NULL DEFAULT 0,
  total numeric(14,2) NOT NULL DEFAULT 0,
  amount_paid numeric(14,2) NOT NULL DEFAULT 0,
  issue_date date,
  due_date date,            -- invoices: pay by; quotes: valid until
  notes text,
  terms text,
  issuer jsonb,             -- copy of invoice_settings taken at issue, so later edits never change an issued document
  public_token text,        -- unguessable link token (INV-3 public page)
  converted_from_id uuid REFERENCES invoices(id) ON DELETE SET NULL,   -- invoice made from this quote
  payment_link_id uuid REFERENCES payment_links(id) ON DELETE SET NULL,
  created_by uuid REFERENCES users(id),
  issued_at timestamptz,
  issued_by uuid REFERENCES users(id),
  sent_at timestamptz,
  accepted_at timestamptz,
  declined_at timestamptz,
  voided_at timestamptz,
  voided_by uuid REFERENCES users(id),
  void_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS invoices_org_type_number ON invoices(org_id, doc_type, number) WHERE number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS invoices_public_token ON invoices(public_token) WHERE public_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS invoices_org_created ON invoices(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS invoices_org_lead ON invoices(org_id, lead_id) WHERE lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS invoices_org_customer ON invoices(org_id, customer_id) WHERE customer_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS invoice_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id uuid NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE SET NULL,
  description text NOT NULL,
  quantity numeric(12,2) NOT NULL CHECK (quantity > 0),
  unit_price numeric(14,2) NOT NULL CHECK (unit_price >= 0),
  line_total numeric(14,2) NOT NULL,
  position integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS invoice_items_invoice ON invoice_items(invoice_id, position);

-- One row per payment received (INV-4 fills it). invoice_id NULL = a standalone receipt for a walk-in sale.
CREATE TABLE IF NOT EXISTS receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  number text NOT NULL,
  invoice_id uuid REFERENCES invoices(id) ON DELETE SET NULL,
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
  customer_name text,
  amount numeric(14,2) NOT NULL CHECK (amount > 0),
  currency text NOT NULL DEFAULT 'NGN',
  method text NOT NULL CHECK (method IN ('paystack','bank_transfer','cash','pos','ussd','other')),
  reference text,
  proof_path text,
  description text,
  paid_at timestamptz NOT NULL DEFAULT now(),
  recorded_by uuid REFERENCES users(id),     -- NULL = recorded by the Paystack webhook
  payment_link_id uuid REFERENCES payment_links(id) ON DELETE SET NULL,
  issuer jsonb,
  public_token text,
  voided_at timestamptz,
  voided_by uuid REFERENCES users(id),
  void_reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS receipts_org_number ON receipts(org_id, number);
CREATE UNIQUE INDEX IF NOT EXISTS receipts_public_token ON receipts(public_token) WHERE public_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS receipts_payment_link ON receipts(payment_link_id) WHERE payment_link_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipts_org_invoice ON receipts(org_id, invoice_id);

-- Number counters. next_invoice_number() hands out 1, 2, 3 ... per business and kind in one atomic statement,
-- so two staff issuing at the same moment can never get the same number.
CREATE TABLE IF NOT EXISTS invoice_counters (
  org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('quote','invoice','receipt')),
  next_value integer NOT NULL DEFAULT 1,
  PRIMARY KEY (org_id, kind)
);

CREATE OR REPLACE FUNCTION next_invoice_number(p_org uuid, p_kind text) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  INSERT INTO invoice_counters (org_id, kind, next_value) VALUES (p_org, p_kind, 2)
  ON CONFLICT (org_id, kind) DO UPDATE SET next_value = invoice_counters.next_value + 1
  RETURNING next_value - 1;
$$;
REVOKE ALL ON FUNCTION next_invoice_number(uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION next_invoice_number(uuid, text) TO service_role;

-- RLS: same posture as other server-only tables (backend uses the service role).
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['invoice_settings','invoices','invoice_items','receipts','invoice_counters'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = t::regclass AND polname = 'service_role_bypass') THEN
      EXECUTE format('CREATE POLICY service_role_bypass ON %I TO service_role USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;
