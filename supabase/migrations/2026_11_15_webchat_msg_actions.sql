-- WEBCHAT-MSG-1: visitors can reply to, edit and delete messages in the web chat (WhatsApp style).
-- Additive only. original_content keeps what was said before an edit or a delete, for the team's record.
ALTER TABLE public.whatsapp_messages
  ADD COLUMN IF NOT EXISTS reply_to_id uuid,
  ADD COLUMN IF NOT EXISTS edited_at timestamptz,
  ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
  ADD COLUMN IF NOT EXISTS original_content text;
