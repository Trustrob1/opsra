-- RETURN-MENU-1: show the WhatsApp menu again to returning leads and customers. On by default; an org can switch it off.
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS returning_menu_enabled boolean NOT NULL DEFAULT true;
