"""WEBCHAT-ATTACH-1: visitor files are accepted only when their real bytes match an allowed type and size."""
import io
import zipfile

from app.services import webchat_attachment_service as att
from app.services import webchat_service as wc

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"x" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64


def _zip(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


def test_good_files_pass():
    for data, kind, name, mime in [
        (JPEG, "image", "bed.jpg", "image/jpeg"), (PNG, "image", "bed.png", "image/png"),
        (PDF, "document", "quote.pdf", "application/pdf"),
        (_zip("word/document.xml"), "document", "order.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (WEBM, "audio", "blob", "audio/webm"), (OGG, "audio", "v.ogg", "audio/ogg"), (MP4, "audio", "v.m4a", "audio/mp4"),
    ]:
        clean, err = att.validate(data, kind, name)
        assert err is None and clean["mime"] == mime, (name, err)


def test_the_browsers_word_is_not_trusted():
    # html or an executable renamed to .jpg / .pdf is refused because the first bytes are wrong
    for data, kind, name in [(b"<html><script>alert(1)</script>", "image", "x.jpg"), (b"MZ" + b"\x00" * 64, "document", "x.pdf"),
                             (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image", "x.svg"), (b"PK\x03\x04junk", "document", "x.docx")]:
        clean, err = att.validate(data, kind, name)
        assert clean is None and err, name


def test_kind_must_match_the_bytes():
    assert att.validate(PDF, "image", "a.jpg")[1]
    assert att.validate(JPEG, "audio", "a.webm")[1]
    assert att.validate(JPEG, "video", "a.mp4")[1]          # video is not accepted


def test_zip_without_word_parts_is_refused():
    assert att.validate(_zip("random.txt"), "document", "a.docx")[1]
    assert att.validate(_zip("word/document.xml"), "document", "a.zip")[1]     # wrong extension


def test_size_limits():
    assert att.validate(JPEG + b"0" * (10 * 1024 * 1024), "image", "big.jpg")[1]
    assert att.validate(WEBM + b"0" * (5 * 1024 * 1024), "audio", "big.webm")[1]
    assert att.validate(b"", "image", "empty.jpg")[1]


def test_filename_is_made_safe():
    assert att.clean_filename("../../etc/passwd", "document", "pdf") == "passwd.pdf"
    assert att.clean_filename("my <bed>.JPG", "image", "jpg").endswith(".jpg")
    assert "/" not in att.clean_filename("a/b\\c.pdf", "document", "pdf")
    assert att.clean_filename("", "audio", "webm") == "voice-note.webm"


class _Bucket:
    def __init__(self): self.uploaded = []
    def upload(self, path, file, file_options): self.uploaded.append((path, len(file), file_options))
    def create_signed_url(self, path, expires_in): return {"signedUrl": "https://files.example/" + path}


class _Storage:
    def __init__(self): self.b = _Bucket()
    def from_(self, name): assert name == "whatsapp-media"; return self.b


class _Q:
    def __init__(self, sink): self.sink = sink
    def insert(self, row): self.sink.append(row); return self
    def execute(self): return self


class _DB:
    def __init__(self): self.storage = _Storage(); self.rows = []
    def table(self, name): assert name == "whatsapp_messages"; return _Q(self.rows)


def test_save_attachment_stores_file_and_inbox_row():
    db = _DB()
    s = {"id": "s1", "org_id": "o1", "lead_id": "l1"}
    clean, _ = att.validate(JPEG, "image", "bed.jpg")
    msg = att.save_attachment(db, s, "image", clean, JPEG)
    path = db.storage.b.uploaded[0][0]
    assert path.startswith("o1/webchat/s1/") and path.endswith("_bed.jpg")
    row = db.rows[0]
    assert row["message_type"] == "image" and row["direction"] == "inbound" and row["channel"] == "webchat"
    assert row["storage_path"] == path and row["media_url"].endswith(path) and row["lead_id"] == "l1"
    assert msg["role"] == "visitor" and msg["attachment"]["kind"] == "image"


def test_voice_note_text_is_plain():
    db = _DB()
    s = {"id": "s1", "org_id": "o1", "lead_id": "l1"}
    clean, _ = att.validate(WEBM, "audio", "blob")
    assert att.save_attachment(db, s, "audio", clean, WEBM)["text"] == "Voice note"


def test_list_output_carries_attachment():
    out = wc._out("visitor", {"id": "m1", "content": "bed.jpg", "created_at": "t", "message_type": "image", "media_url": "https://x/y"})
    assert out["attachment"] == {"kind": "image", "name": "bed.jpg", "url": "https://x/y"}
    assert "attachment" not in wc._out("bot", {"id": "m2", "content": "hi", "created_at": "t", "message_type": "text"})
