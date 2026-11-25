-- REPORT-1: per-rep payment confirmation, named confirmers, emailed owner reports.
ALTER TABLE invoice_settings
  ADD COLUMN IF NOT EXISTS payment_confirm_reps  uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS payment_confirmers    uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS report_emails         text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS daily_sales_report    boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS weekly_reports        boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS last_daily_report_on  date,
  ADD COLUMN IF NOT EXISTS last_weekly_report_on date;

-- Royal Rest: reports to the owner's email, daily and weekly on.
UPDATE invoice_settings
   SET report_emails = ARRAY['info.royalrest@gmail.com'],
       daily_sales_report = true,
       weekly_reports = true
 WHERE org_id = '00b381e2-9c74-42ff-8017-afb762b4b564';

-- Check: should return 7 and 1.
SELECT (SELECT count(*) FROM information_schema.columns
         WHERE table_name = 'invoice_settings'
           AND column_name IN ('payment_confirm_reps','payment_confirmers','report_emails','daily_sales_report',
                               'weekly_reports','last_daily_report_on','last_weekly_report_on')) AS cols_should_be_7,
       (SELECT count(*) FROM invoice_settings
         WHERE org_id = '00b381e2-9c74-42ff-8017-afb762b4b564' AND daily_sales_report) AS royal_rest_on;
