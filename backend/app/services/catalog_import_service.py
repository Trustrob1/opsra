"""
app/services/catalog_import_service.py
--------------------------------------
STORE-10: add many products at once from a spreadsheet (CSV or Excel .xlsx), and attach photos from web links.

Columns (the heading can be written many ways; only Title is required):
  Title            the product name
  Price            150000, 150,000 or N150,000 (empty means customers must ask)
  Description      free text
  Category         one or more, separated by commas
  Sizes            Single 3/4 ft=120000; Queen 5/6 ft=180000   (a size with no price uses the product price;
                   a plain list such as "Single, Queen" also works)
  Photos           one or more https links, separated by spaces or commas (also see "drop a folder of photos")
  In stock         yes / no (empty means yes)

A row whose title starts with the capital word EXAMPLE (the two sample rows in the template) is skipped, so sample rows
can be left in the file by mistake without being added.
The owner always sees a preview first. Nothing is guessed: a row with a problem is listed with the reason and skipped,
and a product whose name already exists is skipped (never duplicated or overwritten).
Photos are fetched one at a time by the page (progress bar), through fetch_image(), which refuses anything that is not a
public https picture of 5 MB or less.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import logging
import re
import socket
from typing import Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_ROWS = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SIZES = 20
MAX_PHOTOS = 5
EXAMPLE_RE = re.compile(r"^EXAMPLE\b")
MAX_TITLE = 200
MAX_IMAGE_BYTES = 5 * 1024 * 1024
TEMPLATE_HEADERS = ["Title", "Price", "Description", "Category", "Sizes", "Photos", "In stock"]
TEMPLATE_ROWS = [
    ["EXAMPLE Cloud 9 Mattress", "150000", "Soft, supportive and cool to sleep on.", "Mattresses",
     "Single 3/4 ft=120000; Queen 5/6 ft=180000", "https://example.com/cloud9.jpg", "yes"],
    ["EXAMPLE Memory Foam Pillow", "12000", "", "Pillows, Bedding", "", "", "yes"],
]

ALIASES = {
    "title": {"title", "name", "productname", "product", "item", "itemname", "producttitle"},
    "price": {"price", "amount", "cost", "sellingprice", "unitprice"},
    "description": {"description", "details", "about", "info"},
    "category": {"category", "categories", "collection", "collections", "type", "group"},
    "sizes": {"sizes", "size", "options", "variants", "variations"},
    "photos": {"photos", "photo", "photolinks", "photolink", "photourl", "images", "image", "imagelinks", "imagelink",
               "imageurl", "pictures", "picture", "links"},
    "in_stock": {"instock", "available", "stock", "availability"},
}
_YES = {"yes", "y", "true", "1", "in stock", "instock", "available"}
_NO = {"no", "n", "false", "0", "out", "out of stock", "outofstock", "sold out", "soldout", "unavailable"}


class FileProblem(ValueError):
    """A problem with the file as a whole; the message is for the owner."""


# ── Reading the file ────────────────────────────────────────────────────────

def _key(heading) -> str:
    return re.sub(r"[^a-z0-9]", "", str(heading or "").lower())


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _read_csv(data: bytes) -> List[List[str]]:
    text = _decode(data)
    first = text.split("\n", 1)[0]
    delim = max([",", ";", "\t"], key=lambda d: first.count(d))
    return [[c for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _read_xlsx(data: bytes) -> List[List[str]]:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else (str(int(c)) if isinstance(c, float) and c.is_integer() else str(c)) for c in r])
            if len(rows) > MAX_ROWS + 50:
                break
        return rows
    except FileProblem:
        raise
    except Exception as exc:
        logger.warning("xlsx read failed: %s", exc)
        raise FileProblem("We could not read that Excel file. Save it again as .xlsx or .csv and try once more.")


def read_table(data: bytes, filename: str) -> List[List[str]]:
    if not data:
        raise FileProblem("That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise FileProblem("That file is too big. Keep it under 2 MB (about 500 products without pictures).")
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        return _read_xlsx(data)
    if name.endswith(".xls"):
        raise FileProblem("Old Excel files (.xls) are not supported. Open it and choose Save As .xlsx or .csv.")
    if name.endswith(".csv") or name.endswith(".txt") or not name:
        return _read_csv(data)
    raise FileProblem("Please use a .csv or .xlsx file.")


# ── Cleaning one cell at a time ─────────────────────────────────────────────

def parse_price(raw) -> Optional[float]:
    """150000 | 150,000 | N150,000 | ₦150 000 | 150000.50. Empty gives None. Anything else raises ValueError."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    s = re.sub(r"(?i)^\s*(ngn|n|₦)\s*", "", s)
    s = s.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        raise ValueError(f"The price '{str(raw).strip()}' is not a number.")
    v = float(s)
    if v < 0 or v > 1_000_000_000:
        raise ValueError(f"The price '{str(raw).strip()}' is not usable.")
    return v


def parse_in_stock(raw) -> bool:
    s = str(raw or "").strip().lower()
    if s in _NO:
        return False
    return True


def parse_sizes(raw) -> List[dict]:
    """'Single=120000; Queen=180,000' or 'Single, Queen'. Returns [{title, price|None}]. Raises ValueError on a bad price."""
    text = str(raw or "").strip()
    if not text:
        return []
    chunks = [c for c in re.split(r"[;|\n]+", text) if c.strip()]
    if len(chunks) == 1 and "=" not in chunks[0] and ":" not in chunks[0]:
        chunks = [c for c in chunks[0].split(",") if c.strip()]
    out, seen = [], set()
    for c in chunks:
        m = re.match(r"^(.*?)\s*[=:]\s*(.+)$", c.strip())
        title, price = (m.group(1).strip(), parse_price(m.group(2))) if m else (c.strip(), None)
        title = " ".join(title.split())[:60]
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append({"title": title, "price": price})
    if len(out) > MAX_SIZES:
        raise ValueError(f"A product can have up to {MAX_SIZES} sizes.")
    return out


def parse_list(raw) -> List[str]:
    seen, out = set(), []
    for part in re.split(r"[,;|\n]+", str(raw or "")):
        p = " ".join(part.split())
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def parse_photos(raw) -> tuple:
    """(https links to use, notes about links that were left out)."""
    good, notes = [], []
    for part in re.split(r"[\s,;|]+", str(raw or "").strip()):
        if not part:
            continue
        if part.lower().startswith("https://") and urlparse(part).hostname:
            if part not in good:
                good.append(part)
        else:
            notes.append(f"Photo link left out (it must start with https://): {part[:60]}")
    if len(good) > MAX_PHOTOS:
        notes.append(f"Only the first {MAX_PHOTOS} photo links are used.")
        good = good[:MAX_PHOTOS]
    return good, notes


# ── Rows ────────────────────────────────────────────────────────────────────

def parse_table(table: List[List[str]]) -> dict:
    """Headings and rows -> {"rows": [...], "unknown": [headings not used], "found": [fields found]}. Raises FileProblem."""
    table = [r for r in table if any(str(c or "").strip() for c in r)]
    if not table:
        raise FileProblem("That file has no rows.")
    head = table[0]
    col = {}
    unknown = []
    for i, h in enumerate(head):
        k = _key(h)
        field = next((f for f, names in ALIASES.items() if k in names), None)
        if field and field not in col:
            col[field] = i
        elif str(h or "").strip():
            unknown.append(str(h).strip())
    if "title" not in col:
        raise FileProblem("We could not find a Title column. The first row must have headings such as Title, Price, Description.")
    body = table[1:]
    if not body:
        raise FileProblem("That file has headings but no products.")
    if len(body) > MAX_ROWS:
        raise FileProblem(f"That file has {len(body)} products. Please import up to {MAX_ROWS} at a time.")

    def cell(r, f):
        i = col.get(f)
        return r[i] if i is not None and i < len(r) else ""

    rows = []
    for n, r in enumerate(body, start=2):          # row 1 is the headings, so the first product is row 2 as in the sheet
        notes, problems = [], []
        title = " ".join(str(cell(r, "title")).split())
        if not title:
            problems.append("No title.")
        elif len(title) > MAX_TITLE:
            problems.append(f"The title is longer than {MAX_TITLE} characters.")
        price = None
        try:
            price = parse_price(cell(r, "price"))
        except ValueError as e:
            problems.append(str(e))
        sizes = []
        try:
            sizes = parse_sizes(cell(r, "sizes"))
        except ValueError as e:
            problems.append(str(e))
        photos, pnotes = parse_photos(cell(r, "photos"))
        notes.extend(pnotes)
        if price is None and not any(s["price"] for s in sizes) and not problems:
            notes.append("No price: customers will have to ask you about it.")
        rows.append({
            "row": n, "example": bool(EXAMPLE_RE.match(title)), "title": title, "price": price, "description": str(cell(r, "description")).strip()[:5000],
            "categories": parse_list(cell(r, "category")), "sizes": sizes, "photos": photos,
            "available": parse_in_stock(cell(r, "in_stock")), "problems": problems, "notes": notes,
        })
    return {"rows": rows, "unknown": unknown, "found": sorted(col)}


def _existing_titles(db, org_id: str) -> set:
    res = db.table("products").select("title").eq("org_id", org_id).execute()
    return {str(r.get("title") or "").strip().lower() for r in (res.data or [])}


def plan(db, org_id: str, parsed: dict) -> dict:
    """Marks each row ok / exists / duplicate / error and counts them. Writes nothing."""
    have = _existing_titles(db, org_id)
    seen = set()
    counts = {"total": 0, "ok": 0, "exists": 0, "duplicate": 0, "error": 0, "example": 0}
    for r in parsed["rows"]:
        counts["total"] += 1
        low = r["title"].lower()
        if r.get("example"):
            r["status"] = "example"
        elif r["problems"]:
            r["status"] = "error"
        elif low in have:
            r["status"] = "exists"
        elif low in seen:
            r["status"] = "duplicate"
        else:
            r["status"] = "ok"
        if r["status"] == "ok":
            seen.add(low)
        counts[r["status"]] += 1
    cats = sorted({c for r in parsed["rows"] if r["status"] == "ok" for c in r["categories"]}, key=str.lower)
    return {"rows": parsed["rows"], "counts": counts, "categories": cats, "unknown": parsed["unknown"], "found": parsed["found"],
            "photo_links": sum(len(r["photos"]) for r in parsed["rows"] if r["status"] == "ok")}


def run(db, org_id: str, planned: dict, create_item, ensure_categories) -> dict:
    """
    Creates every row marked ok. create_item(db, org_id, payload) and ensure_categories(db, org_id, names) are passed in
    so this stays easy to test. A row that fails is reported, the others still go in.
    Returns {created: [{id, title, slug, photos}], failed: [{row, title, message}], categories_added, categories_skipped}.
    """
    ok = [r for r in planned["rows"] if r["status"] == "ok"]
    wanted = [c for r in ok for c in r["categories"]]
    cat = ensure_categories(db, org_id, wanted) if wanted else {"names": {}, "added": [], "skipped": []}
    created, failed = [], []
    for r in ok:
        cats = [cat["names"][c.lower()] for c in r["categories"] if c.lower() in cat["names"]]
        payload = {
            "title": r["title"], "price": r["price"], "description": r["description"] or None, "available": r["available"],
            "variants": [{"title": s["title"], "price": s["price"], "available": True} for s in r["sizes"]],
            "tags": {"category": cats} if cats else {},
        }
        try:
            item = create_item(db, org_id, payload) or {}
            if not item.get("id"):
                raise RuntimeError("no id")
            created.append({"id": str(item["id"]), "title": r["title"], "slug": item.get("slug"), "photos": r["photos"], "row": r["row"]})
        except Exception as exc:
            logger.warning("catalog import row %s failed org=%s: %s", r["row"], org_id, exc)
            failed.append({"row": r["row"], "title": r["title"], "message": "Could not be added. Please try this one by hand."})
    return {"created": created, "failed": failed, "categories_added": cat["added"], "categories_skipped": cat["skipped"]}


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADERS)
    for r in TEMPLATE_ROWS:
        w.writerow(r)
    return "﻿" + buf.getvalue()           # the mark lets Excel open the naira sign and accents correctly


# ── Pictures from web links ─────────────────────────────────────────────────

def _public_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def sniff_image(head: bytes) -> Optional[str]:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


class PhotoError(ValueError):
    """Why a photo link could not be used; the message is for the owner."""


def fetch_image(url: str, opener=None) -> tuple:
    """
    Download one picture from a public https link. Returns (bytes, mime). Raises PhotoError.
    Refuses: non-https links, addresses inside private networks (checked on every redirect), anything over 5 MB, and
    anything that is not really a JPEG, PNG or WebP picture. Does not follow more than 3 redirects.
    (The address is checked just before the request; a site that changes its address in between is not covered.)
    """
    import httpx
    current = str(url or "").strip()
    for _ in range(4):
        parts = urlparse(current)
        if parts.scheme != "https" or not parts.hostname:
            raise PhotoError("That link must start with https://")
        if not _public_ip(parts.hostname):
            raise PhotoError("That link cannot be used.")
        try:
            with (opener or httpx.stream)("GET", current, timeout=10.0, follow_redirects=False,
                                          headers={"User-Agent": "Opsra-catalog-import/1.0", "Accept": "image/*"}) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location") or ""
                    current = str(httpx.URL(current).join(loc))
                    continue
                if resp.status_code != 200:
                    raise PhotoError("The link did not open a picture. For Google Drive or Dropbox, use a direct picture link.")
                data = b""
                for chunk in resp.iter_bytes():
                    data += chunk
                    if len(data) > MAX_IMAGE_BYTES:
                        raise PhotoError("That picture is bigger than 5 MB.")
        except PhotoError:
            raise
        except Exception as exc:
            logger.info("photo link failed %s: %s", parts.hostname, exc)
            raise PhotoError("We could not download that picture.")
        mime = sniff_image(data[:16])
        if not mime:
            raise PhotoError("That link is not a JPEG, PNG or WebP picture.")
        return data, mime
    raise PhotoError("That link redirects too many times.")
