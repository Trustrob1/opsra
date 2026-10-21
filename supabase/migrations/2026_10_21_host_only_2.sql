-- HOST-3b: marks a domain the client already owns elsewhere (hosting only, no domain to renew). Safe to run twice.
ALTER TABLE site_domains ADD COLUMN IF NOT EXISTS own_domain boolean NOT NULL DEFAULT false;
