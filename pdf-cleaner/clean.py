"""
Jackson AI - PDF Cleaner engine.

clean_pdf(src, dst, opts, progress=print) edits a textbook PDF:
  * removes named boxes / sections (e.g. "Learning Activity", "Key Unit Competence")
  * removes whole parts that run to the end of a chapter (e.g. "End of unit assessment")
  * deletes chosen pages
  * removes repeating footers
  * closes the gaps (re-flows the pages), renumbers pages
  * rebuilds the table of contents with matching page numbers (+ PDF bookmarks)
  * writes your own footer text (e.g. a website) on every page

Text is removed exactly (content-stream editing), so neighbouring text is never lost.
"""
import re, sys, os, json, statistics
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cstream import strip_text
import analyze, reflow

DEFAULTS = dict(
    remove_titles=[],            # boxes / sections that start with one of these titles
    remove_to_chapter_end=[],    # titles whose section runs to the end of the chapter
    drop_pages=[],               # 1-based page numbers or "a-b" ranges (of the ORIGINAL file)
    drop_pages_titled=[],        # delete any page whose top line starts with one of these
    remove_footers=True,
    reflow=True,
    rebuild_toc=True,
    keep_cover=True,
    footer_text="",              # e.g. "https://jacksonhabimana.github.io/jackson-Ai/"
    footer_bold=True,
    chapter_label_regex=r"^(UNIT|CHAPTER|Unit|Chapter)(\s*\d+)?$",
    draw_frame=True,
)

WHITE = (1, 1, 1)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def page_lines(page):
    """lines with exact-ish geometry: dict(text, x0, x1, oy, size, bold, rect)"""
    out = []
    for blk in page.get_text("dict")["blocks"]:
        for l in blk.get("lines", []):
            sp = [s for s in l["spans"] if s["text"].strip()]
            if not sp:
                continue
            t = "".join(s["text"] for s in l["spans"]).strip()
            s0 = sp[0]
            size = max(s["size"] for s in sp)
            oy = s0["origin"][1]
            bold = any((s["flags"] & 16) or "bold" in s["font"].lower() for s in sp)
            out.append(dict(text=t, x0=l["bbox"][0], x1=l["bbox"][2], oy=oy, size=size, bold=bold,
                            rect=pymupdf.Rect(l["bbox"][0], oy - size * 0.95, l["bbox"][2], oy + size * 0.3)))
    out.sort(key=lambda d: (round(d["oy"]), d["x0"]))
    return out


def parse_pages(spec, n):
    res = set()
    for item in spec or []:
        item = str(item).strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", item)
        if m:
            res.update(range(int(m.group(1)) - 1, min(int(m.group(2)), n)))
        elif item.isdigit() and 0 < int(item) <= n:
            res.add(int(item) - 1)
    return res


# ───────────────────────────── removal of boxes / sections ─────────────────────────────
def fills(page):
    out = []
    PW, PH = page.rect.width, page.rect.height
    for x in page.get_drawings():
        f = x.get("fill")
        if not f or x["type"] not in ("f", "fs"):
            continue
        r = x["rect"]
        if tuple(round(c, 2) for c in f) == (1.0, 1.0, 1.0):
            continue
        if r.width * r.height > 0.8 * PW * PH or r.width < 120 or r.height < 28:
            continue
        out.append((r, tuple(round(c, 2) for c in f)))
    return out


def small_fill(page, line):
    """the little coloured pill/label behind a title (if any)"""
    p = pymupdf.Point(line["x0"] + 3, line["oy"] - line["size"] * 0.35)
    u = None
    for x in page.get_drawings():
        r = x["rect"]
        if x["type"] in ("f", "fs") and 90 < r.width < 330 and 12 < r.height < 48 and r.contains(p):
            u = r if u is None else u | r
    return u


def enclosing_box(page, line):
    """(rect, fill) of the coloured box that belongs to a title, else None.
    Handles titles in a pill that straddles the box top, and titles printed inside a box."""
    PH = page.rect.height
    pill = small_fill(page, line)
    allf = fills(page)
    below = [(r, f) for r, f in allf
             if r.x0 - 8 <= line["x0"] <= r.x1 and r.y0 - 45 <= line["oy"] <= r.y1
             and r.y0 >= line["oy"] - line["size"] - 45 and r.y1 > line["oy"] and r.width > 300]
    if below:
        r, f = max(below, key=lambda t: t[0].y0)
        return (r | pill if pill else r), f
    p = pymupdf.Point(line["x0"] + 2, line["oy"] - line["size"] * 0.35)
    inside = [(r, f) for r, f in allf if r.contains(p) and r.width > 150 and r.height > 30 and r.height < PH * 0.6]
    if inside:
        return max(inside, key=lambda t: t[0].width * t[0].height)
    return None


def find_title_hits(doc, pi, titles):
    hits = []
    for ln in page_lines(doc[pi]):
        t = _norm(ln["text"])
        t2 = _norm(re.sub(r"^\d+(\.\d+)*\.?\s*", "", ln["text"]))
        for title in titles:
            if t.startswith(_norm(title)) or t2.startswith(_norm(title)):
                hits.append((title, ln))
                break
    return hits


def heading_end(lines, start_idx, ref, H):
    """y where the section started by lines[start_idx] ends on this page; None = runs to page end"""
    for ln in lines[start_idx + 1:]:
        if ln["oy"] - lines[start_idx]["oy"] < ref["size"] * 1.5:
            continue
        if ln["size"] >= ref["size"] - 0.3 and (ln["bold"] or re.match(r"^\d+(\.\d+)*\.?\s", ln["text"])):
            return ln["oy"] - ln["size"] - 2
    return None


class Remover:
    def __init__(self, doc):
        self.doc = doc
        self.reds = {}
        self.delete = set()
        self.log = []

    def add(self, pi, rect, tag):
        self.reds.setdefault(pi, []).append(pymupdf.Rect(rect))
        self.log.append((pi + 1, tag))

    def apply(self):
        for pi, rs in self.reds.items():
            p = self.doc[pi]
            strip_text(p, rs)
            for r in rs:
                p.add_redact_annot(r, fill=WHITE)
            PW = p.rect.width
            for info in p.get_image_info(xrefs=True):
                b = pymupdf.Rect(info["bbox"])
                if info.get("xref") and any(r.contains(b) for r in rs):
                    try:
                        p.delete_image(info["xref"])
                    except Exception:
                        pass
            p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                               graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                               text=pymupdf.PDF_REDACT_TEXT_NONE)


def remove_boxes(doc, R, titles, progress):
    N = len(doc)
    H = doc[0].rect.height
    count = 0
    for pi in range(N):
        if pi in R.delete:
            continue
        lines = page_lines(doc[pi])
        for title, ln in find_title_hits(doc, pi, titles):
            idx = lines.index(ln)
            box = enclosing_box(doc[pi], ln)
            if box:
                r, fill = box
                R.add(pi, r + (-3, -3, 3, 3), "box:" + title)
                count += 1
                q, rr = pi, r
                while rr.y1 > H * 0.86 and q + 1 < N:      # box continues on the next page
                    nxt = [(a, f) for a, f in fills(doc[q + 1]) if a.y0 < H * 0.17 and f == fill and a.width > 300]
                    if not nxt:
                        break
                    a = min(nxt, key=lambda t: t[0].y0)[0]
                    q += 1
                    R.add(q, a + (-3, -3, 3, 3), "box-cont:" + title)
                    rr = a
            else:
                # plain heading: remove from the heading to the next heading of the same or higher rank
                end = heading_end(lines, idx, ln, H)
                x0 = max(0, min(l["x0"] for l in lines) - 4)
                x1 = doc[pi].rect.width
                top_y = ln["oy"] - ln["size"] - 3
                bottom = end if end else min(H * 0.93, top_y + H * 0.45)   # never swallow more than 45% of a page
                R.add(pi, pymupdf.Rect(x0, top_y, x1, bottom), "heading:" + title)
                count += 1
    progress(f"removed {count} boxes/sections")


def chapter_starts(doc, label_re):
    analyze.OPENER_RE = label_re
    return [pi for pi in range(len(doc)) if analyze.is_opener(doc[pi])]


def remove_to_chapter_end(doc, R, titles, label_re, progress):
    starts = chapter_starts(doc, label_re)
    bounds = starts + [len(doc)]
    n = 0
    H = doc[0].rect.height
    for k in range(len(starts)):
        s, e = bounds[k], bounds[k + 1]
        for pi in range(s, e):
            hits = find_title_hits(doc, pi, titles)
            if not hits:
                continue
            ln = hits[0][1]
            n += 1
            top = ln["oy"] - ln["size"] - 5
            box = enclosing_box(doc[pi], ln)
            if box:
                top = min(top, box[0].y0 - 3)
            if top < H * 0.12:
                R.delete.add(pi)
            else:
                R.add(pi, pymupdf.Rect(0, top, doc[pi].rect.width, H * 0.93), "to-end:" + hits[0][0])
            R.delete.update(range(pi + 1, e))
            break
    progress(f"removed {n} 'to end of chapter' parts")


# ───────────────────────────── footers ─────────────────────────────
def detect_footer_top(doc, body_from=0):
    H = doc[0].rect.height
    cnt = {}
    n = 0
    for pi in range(body_from, len(doc)):
        n += 1
        seen = set()
        for ln in page_lines(doc[pi]):
            if ln["oy"] > H * 0.905:
                key = re.sub(r"\d+", "#", _norm(ln["text"]) if False else re.sub(r"\s+", " ", ln["text"]))
                key = re.sub(r"\d+", "#", key)
                if key not in seen:
                    seen.add(key)
                    cnt[key] = cnt.get(key, 0) + 1
    common = [k for k, v in cnt.items() if v >= max(5, 0.25 * n) and len(k) > 0]
    if not common:
        return None
    ys = []
    for pi in range(body_from, min(len(doc), body_from + 60)):
        for ln in page_lines(doc[pi]):
            if ln["oy"] > H * 0.905 and re.sub(r"\d+", "#", re.sub(r"\s+", " ", ln["text"])) in common:
                ys.append(ln["rect"].y0)
    return (min(ys) - 8) if ys else None


def remove_footers(doc, R, first_page, progress):
    ft = detect_footer_top(doc, first_page)
    if ft is None:
        progress("no repeating footer found")
        return None
    W = doc[0].rect.width
    for pi in range(len(doc)):
        if pi < first_page or pi in R.delete:
            continue
        R.add(pi, pymupdf.Rect(0, ft, W, doc[pi].rect.height), "footer")
    progress(f"footer strip found at y>{ft:.0f}")
    return ft


# ───────────────────────────── geometry of the text area ─────────────────────────────
def text_area(doc, pages, foot_top):
    H = doc[0].rect.height
    x0s, x1s, y0s, y1s = [], [], [], []
    for pi in pages[::max(1, len(pages) // 120)]:
        for ln in page_lines(doc[pi]):
            if foot_top and ln["oy"] > foot_top:
                continue
            if len(ln["text"]) < 8:
                continue
            x0s.append(ln["x0"]); x1s.append(ln["x1"]); y0s.append(ln["rect"].y0); y1s.append(ln["oy"])
    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, max(0, int(q * len(v))))]
    fx0 = max(10, pct(x0s, 0.03) - 8)
    fx1 = min(doc[0].rect.width - 10, pct(x1s, 0.97) + 8)
    top = max(20, pct(y0s, 0.01) - 8)
    bot = min(foot_top or H * 0.93, pct(y1s, 0.995) + 10)
    return fx0, fx1, top, bot


# ───────────────────────────── main ─────────────────────────────
def clean_pdf(src, dst, opts=None, progress=print):
    o = dict(DEFAULTS)
    o.update(opts or {})
    doc = pymupdf.open(src)
    N0 = len(doc)
    H = doc[0].rect.height
    W = doc[0].rect.width
    progress(f"opened {N0} pages")
    R = Remover(doc)

    R.delete |= parse_pages(o["drop_pages"], N0)
    for pi in range(N0):
        lines = [l for l in page_lines(doc[pi]) if l["oy"] < H * 0.2]
        for l in lines[:3]:
            if o["drop_pages_titled"] and any(_norm(l["text"]).startswith(_norm(t)) for t in o["drop_pages_titled"]):
                R.delete.add(pi)
    if o["keep_cover"]:
        R.delete.discard(0)

    if o["remove_titles"]:
        remove_boxes(doc, R, o["remove_titles"], progress)
    if o["remove_to_chapter_end"]:
        remove_to_chapter_end(doc, R, o["remove_to_chapter_end"], o["chapter_label_regex"], progress)
    first_body = 1 if o["keep_cover"] else 0
    foot_top = remove_footers(doc, R, first_body, progress) if o["remove_footers"] else None
    R.apply()
    progress("text and boxes removed")

    # delete pages (and the table of contents pages are rebuilt below)
    keep = [pi for pi in range(N0) if pi not in R.delete]
    doc.select(keep)
    progress(f"{len(keep)} pages kept")

    # table of contents of the ORIGINAL book is dropped when we rebuild it
    label_re = o["chapter_label_regex"]
    analyze.OPENER_RE = label_re
    openers = [pi for pi in range(len(doc)) if analyze.is_opener(doc[pi])]
    body_first = openers[0] if openers else (1 if o["keep_cover"] else 0)
    cover_pages = list(range(0, 1)) if o["keep_cover"] and body_first > 0 else []
    if not o["reflow"]:
        for pi in range(len(doc)):
            if o["footer_text"]:
                _footer_text(doc[pi], o)
        doc.save(dst, garbage=4, deflate=True, use_objstms=1)
        return dict(pages=len(doc))

    fx0, fx1, top, bot = text_area(doc, list(range(body_first, len(doc))), foot_top if foot_top is None else None)
    # after the footer strip is white, anything below `bot` is empty anyway
    analyze.FRAME = pymupdf.Rect(fx0, top - 2, fx1, bot + 2)
    analyze.TOP = top
    analyze.BOT = bot
    reflow.TOPY = top + 9
    reflow.BOTY = bot - 3
    progress(f"text area x {fx0:.0f}-{fx1:.0f}, y {top:.0f}-{bot:.0f}")

    # chapter titles for the plain chapter header
    reflow.OPEN_TITLES.clear()
    for pn in openers:
        num, ttl, lab = "", [], "UNIT"
        for blk in doc[pn].get_text("dict")["blocks"]:
            for l in blk.get("lines", []):
                tx = "".join(s["text"] for s in l["spans"]).strip()
                y = l["bbox"][1]
                if y < 200 and tx and re.match(label_re, tx):
                    lab = re.sub(r'\s*\d+$', '', tx)
                    if re.search(r'\d', tx): num = re.sub(r'\D', '', tx)
                elif y < 200 and tx:
                    if re.fullmatch(r"\d+", tx):
                        num = tx
                    else:
                        ttl.append((y, l["bbox"][0], tx))
        ttl.sort()
        reflow.OPEN_TITLES[pn] = (num, " ".join(z for _, _, z in ttl), lab)

    first, last = body_first, len(doc)
    progress("analysing pages...")
    res = reflow.analyze_all(doc, first, last)
    bands = reflow.make_bands(doc, res, first, last)
    pages = reflow.pack(bands)
    progress(f"re-flowed into {len(pages)} pages")

    # ---- render the new body
    out = pymupdf.open()
    for pi in cover_pages:
        out.insert_pdf(doc, from_page=pi, to_page=pi)
    ncover = len(out)
    nfx0, nfx1 = fx0, fx1
    heads = []     # (level, text, body page no)
    seen_h = set()
    sec_by_page = {}
    sizes = []
    for pn in range(first, last):
        sizes += [l["size"] for l in page_lines(doc[pn])]
    body_size = statistics.median(sizes) if sizes else 10
    for pn in range(first, last):
        ls = page_lines(doc[pn])
        for i, l in enumerate(ls):
            if re.match(r"^\d+\.\d+\.?\s*[A-Za-z(]", l["text"]) and (l["bold"] or l["size"] >= body_size + 0.8) \
                    and len(l["text"]) < 160 and not re.match(r"^\d+\.\d+\.\d+", l["text"]):
                t = l["text"]
                j = i + 1
                while j < len(ls) and ls[j]["size"] >= l["size"] - 0.3 and ls[j]["oy"] - ls[j - 1]["oy"] < l["size"] * 1.7 \
                        and ls[j]["bold"] == l["bold"] and not re.match(r"^\d+\.", ls[j]["text"]) and len(t) < 160:
                    t += " " + ls[j]["text"]; j += 1
                t = re.sub(r"\s+", " ", t).replace(chr(0x2019), chr(39))
                t = re.sub(r"^(\d+\.\d+)\.?\s*", r"\1. ", t)
                sec_by_page.setdefault(pn, []).append((l["oy"] - l["size"] * 0.5, t))
    for pi, pg in enumerate(pages):
        num = pi + 1
        p = out.new_page(width=W, height=H)
        if o["draw_frame"]:
            p.draw_rect(pymupdf.Rect(nfx0, top - 2, nfx1, bot + 2), color=(0.70, 0.78, 0.90), width=0.8, radius=0.02)
        for c in reflow.chunks_of(pg):
            if c["kind"] == "banner":
                b = c["band"]
                BL = (0.05, 0.35, 0.65)
                x, y = nfx0 + 6, c["dy"]
                lab = (b.get("label") or "UNIT") + (" " + b["num"] if b["num"] else "")
                p.insert_text((x, y + 16), lab, fontname="hebo", fontsize=13, color=(0.35, 0.35, 0.4))
                yy = y + 16
                for ln in b["tlines"]:
                    yy += 24
                    p.insert_text((x, yy), ln, fontname="hebo", fontsize=19, color=BL)
                p.draw_line((x, yy + 9), (nfx1 - 6, yy + 9), color=BL, width=1.5)
                heads.append((1, (lab + ": " if b["num"] else "") + " ".join(b["tlines"]), num))
            else:
                clip = pymupdf.Rect(c["fx0"], c["y0"] - 0.7, c["fx1"], c["y1"] + 0.7)
                dest = pymupdf.Rect(nfx0, c["dy"] - 0.7, nfx1, c["dy"] + (c["y1"] - c["y0"]) + 0.7)
                p.show_pdf_page(dest, doc, c["pn"], clip=clip)
        s = str(num)
        tw = pymupdf.get_text_length(s, fontname="helv", fontsize=10)
        p.insert_text(((W - tw) / 2, H - 52), s, fontname="helv", fontsize=10, color=(0.25, 0.25, 0.35))
        if o["footer_text"]:
            _footer_text(p, o)
        for pl in pg:
            if pl["band"]["kind"] == "banner":
                continue
            for hp in sec_by_page.get(pl["pn"], []):
                if pl["y0"] - 1.5 <= hp[0] <= pl["y1"] + 1.5 and (hp[1], hp[0]) not in seen_h:
                    seen_h.add((hp[1], hp[0]))
                    heads.append((2, hp[1], num))

    # ---- table of contents
    if o["rebuild_toc"] and heads:
        tocdoc = _make_toc(heads, W, H, o)
        ntoc = len(tocdoc)
        final = pymupdf.open()
        final.insert_pdf(out, from_page=0, to_page=ncover - 1) if ncover else None
        final.insert_pdf(tocdoc)
        final.insert_pdf(out, from_page=ncover, to_page=len(out) - 1)
        off = ncover + ntoc
        bm = [[1, "Contents", ncover + 1]] + [[lvl, t, off + pg_] for lvl, t, pg_ in heads]
        _links(final, tocdoc, heads, ncover, off, o)
        try:
            final.set_toc(bm)
        except Exception:
            pass
    else:
        final = out
        final.set_toc([[lvl, t, ncover + pg_] for lvl, t, pg_ in heads])
    final.save(dst, garbage=4, deflate=True, use_objstms=1)
    progress(f"saved {len(final)} pages")
    return dict(pages=len(final), body_pages=len(pages), toc_entries=len(heads))


def _footer_text(page, o):
    W, H = page.rect.width, page.rect.height
    f = "hebo" if o["footer_bold"] else "helv"
    ww = pymupdf.get_text_length(o["footer_text"], fontname=f, fontsize=9)
    page.insert_text(((W - ww) / 2, H - 36), o["footer_text"], fontname=f, fontsize=9, color=(0, 0, 0))
    if o["footer_text"].lower().startswith("http"):
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect((W - ww) / 2, H - 46, (W + ww) / 2, H - 33), "uri": o["footer_text"]})


# ───────────────────────────── TOC pages ─────────────────────────────
def _wrap(t, f, s, w):
    out, cur = [], ""
    for wd in t.split():
        c = (cur + " " + wd).strip()
        if pymupdf.get_text_length(c, fontname=f, fontsize=s) > w and cur:
            out.append(cur); cur = wd
        else:
            cur = c
    out.append(cur)
    return out


def _layout_toc(heads, W, H, L, R):
    blocks, cur = [], None
    for lvl, t, pg in heads:
        if lvl == 1 or cur is None:
            cur = []
            blocks.append(cur)
        cur.append((lvl, t, pg))
    pages, y = [[]], 0
    TOP, BOT = 100, H - 100
    def h(items):
        tot = 0
        for lvl, t, pg in items:
            f, s = ("hebo", 11) if lvl == 1 else ("helv", 10)
            n = len(_wrap(t, f, s, R - L - 40 - (0 if lvl == 1 else 16)))
            tot += n * 14 + (5 if lvl == 1 else 2)
        return tot + 8
    for b in blocks:
        hh = h(b)
        if pages[-1] and y + hh > BOT - TOP:
            pages.append([]); y = 0
        pages[-1].append(b); y += hh
    return pages


def _make_toc(heads, W, H, o):
    L, R = 72, W - 72
    BLUE, DK = (0.05, 0.35, 0.65), (0.1, 0.1, 0.15)
    doc = pymupdf.open()
    laid = _layout_toc(heads, W, H, L, R)
    romans = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    for pi, blocks in enumerate(laid):
        p = doc.new_page(width=W, height=H)
        yy = 100
        if pi == 0:
            p.insert_text((L, 78), "Contents", fontname="hebo", fontsize=20, color=BLUE)
            p.draw_line((L, 86), (R, 86), color=BLUE, width=1.2)
        for items in blocks:
            for lvl, t, pg in items:
                f, s = ("hebo", 11) if lvl == 1 else ("helv", 10)
                x = L if lvl == 1 else L + 16
                lines = _wrap(t.replace("’", "'"), f, s, R - L - 40 - (0 if lvl == 1 else 16))
                yy += 5 if lvl == 1 else 2
                for li, ln in enumerate(lines):
                    yy += 14
                    xx = x + (12 if li else 0)
                    p.insert_text((xx, yy), ln, fontname=f, fontsize=s, color=BLUE if lvl == 1 else DK)
                    if li == len(lines) - 1:
                        n = str(pg); nw = pymupdf.get_text_length(n, fontname=f, fontsize=s)
                        p.insert_text((R - nw, yy), n, fontname=f, fontsize=s, color=BLUE if lvl == 1 else DK)
                        x0 = xx + pymupdf.get_text_length(ln, fontname=f, fontsize=s) + 4
                        x1 = R - nw - 4
                        dw = pymupdf.get_text_length(". ", fontname="helv", fontsize=s)
                        k = int((x1 - x0) / dw)
                        if k > 0:
                            p.insert_text((x1 - k * dw, yy), ". " * k, fontname="helv", fontsize=s, color=(0.5, 0.5, 0.55))
            yy += 8
        r = romans[pi] if pi < len(romans) else str(pi + 1)
        w = pymupdf.get_text_length(r, fontname="helv", fontsize=10)
        p.insert_text(((W - w) / 2, H - 52), r, fontname="helv", fontsize=10, color=(0.25, 0.25, 0.35))
        if o["footer_text"]:
            _footer_text(p, o)
    doc._laid = laid
    return doc


def _links(final, tocdoc, heads, ncover, off, o):
    W, H = final[0].rect.width, final[0].rect.height
    L, R = 72, W - 72
    yy_page = {}
    laid = tocdoc._laid
    for pi, blocks in enumerate(laid):
        page = final[ncover + pi]
        yy = 100
        for items in blocks:
            for lvl, t, pg in items:
                f, s = ("hebo", 11) if lvl == 1 else ("helv", 10)
                n = len(_wrap(t.replace("’", "'"), f, s, R - L - 40 - (0 if lvl == 1 else 16)))
                yy += 5 if lvl == 1 else 2
                top = yy
                yy += 14 * n
                page.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(L, top + 2, R, yy + 3), "page": off + pg - 1, "to": pymupdf.Point(0, 60)})
            yy += 8


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--opts", default="{}")
    a = ap.parse_args()
    print(clean_pdf(a.src, a.dst, json.loads(a.opts)))
