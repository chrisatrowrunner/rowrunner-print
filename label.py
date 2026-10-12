"""Render a RowRunner food label as a Pillow image.

Black text on white; the ⚠ note (if any) is drawn in pure red so brother_ql's
two-color conversion (red=True) prints it on the red channel of a black/red roll.
The RowRunner logo is placed at the top (converted to crisp black-on-white).

NEVER render the `code` column — it is hidden by design and the runner must get
the 6-digit code from the guest.

Two label stocks are supported (selected by LABEL_SIZE in .env):
  "62"    → 62mm continuous, 696 px printable width, variable length.
  "29x90" → 29x90 die-cut, 306 px wide × 991 px long, tighter layout.
"""
import os

from PIL import Image, ImageDraw, ImageFont

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)  # pure red so brother_ql detects it for the red channel

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo-lockup-navy.png")

# printable geometry per brother_ql label id
LABEL_SPECS = {
    "62": {"width": 696, "length": None},       # continuous → length grows with content
    "29x90": {"width": 306, "length": 991},     # die-cut → fixed length
}

# Font candidates tried in order (macOS dev box first, then Windows venue PC, then Linux).
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(size, bold, override):
    candidates = ([override] if override else []) + (
        _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _text_width(draw, text, font):
    l, _, r, _ = draw.textbbox((0, 0), text, font=font)
    return r - l


def _line_height(font):
    """True vertical footprint of a line (ascent + descent) — prevents clipping."""
    try:
        a, d = font.getmetrics()
        return a + d
    except AttributeError:
        _, _, _, b = font.getbbox("Ag")
        return b


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap; hard-splits any single word too wide for the label."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_width(draw, trial, font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _fmt_line(line):
    """Format one order line dict into 'qty× name (option)' + addon strings."""
    qty = line.get("qty") or 1
    name = (line.get("name") or "Item").strip()
    head = "{}× {}".format(qty, name)  # × sign
    option = (line.get("option") or "").strip()
    if option:
        head += " ({})".format(option)
    addons = [a for a in (line.get("addons") or []) if str(a).strip()]
    return head, addons


def _seat_str(seat):
    """Mirror of the apps' src/lib/seat.ts `text` — keep in sync.

    Zone venues (unnumbered seating, e.g. the URI Soccer Complex) carry a
    `label` ("Section A2" / "Zone B") and `detail` ("South bleachers");
    numbered venues fall back to section/row/seat.
    """
    seat = seat or {}
    label = (seat.get("label") or "").strip()
    if label:
        detail = (seat.get("detail") or "").strip()
        return "{} · {}".format(label, detail) if detail else label
    return "Sec {} · Row {} · Seat {}".format(
        seat.get("section", "?"), seat.get("row", "?"), seat.get("seat", "?"))


def _warning_triangle(draw, x, y, size, color):
    """Draw a hollow warning triangle with a '!' — a reliable stand-in for ⚠️."""
    h = size
    w = int(size * 1.15)
    top = (x + w / 2, y)
    left = (x, y + h)
    right = (x + w, y + h)
    lw = max(2, size // 12)
    draw.line([top, left, right, top], fill=color, width=lw, joint="curve")
    ex = x + w / 2
    draw.line([(ex, y + h * 0.32), (ex, y + h * 0.66)], fill=color, width=lw)
    r = max(2, lw)
    draw.ellipse([ex - r, y + h * 0.74, ex + r, y + h * 0.74 + 2 * r], fill=color)
    return w


def _load_logo(max_width):
    """Load the RowRunner logo as crisp black-on-white RGB, scaled to max_width.

    The source is navy artwork on a transparent background; we flatten it onto
    white and threshold to pure black so it prints sharp on a thermal head.
    Returns None if the asset is missing (label still renders, just without it).
    """
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except (OSError, IOError):
        return None
    # flatten onto white using the alpha channel (keeps the bird's eye white)
    flat = Image.new("RGB", logo.size, WHITE)
    flat.paste(logo, mask=logo.split()[3])
    # navy → black, background → white
    bw = flat.convert("L").point(lambda p: 0 if p < 200 else 255).convert("RGB")
    if bw.width > max_width:
        h = round(bw.height * (max_width / bw.width))
        bw = bw.resize((max_width, h), Image.LANCZOS)
    return bw


def render_label(order, label_size="62", red_enabled=True, show_logo=True,
                 font_bold_path="", font_regular_path=""):
    """Build and return an RGB Pillow image for one order row."""
    spec = LABEL_SPECS.get(str(label_size), LABEL_SPECS["62"])
    width = spec["width"]
    fixed_length = spec["length"]

    scale = width / 696.0
    margin = max(10, int(24 * scale))
    content_w = width - 2 * margin

    def B(px):
        return _font(max(9, int(px * scale)), True, font_bold_path)

    def R(px):
        return _font(max(9, int(px * scale)), False, font_regular_path)

    f_order = B(70)
    f_seat = B(40)
    f_guest = R(34)
    f_item = B(38)
    f_addon = R(30)
    f_note = B(40)
    f_foot = R(24)

    scratch = ImageDraw.Draw(Image.new("RGB", (width, 10), WHITE))
    elements = []
    y = margin

    def gap(px):
        nonlocal y
        y += max(3, int(px * scale))

    def add_text(text, font, color=BLACK, indent=0, lead=8):
        nonlocal y
        lh = _line_height(font)
        for ln in _wrap(scratch, text, font, content_w - indent):
            elements.append({"kind": "text", "text": ln, "font": font,
                             "color": color, "x": margin + indent, "y": y})
            y += lh + int(lead * scale)

    def add_hr():
        nonlocal y
        gap(8)
        elements.append({"kind": "hr", "y": y})
        y += max(2, int(3 * scale))
        gap(10)

    # ── logo ──
    if show_logo:
        logo = _load_logo(content_w)
        if logo is not None:
            lx = margin + (content_w - logo.width) // 2
            elements.append({"kind": "image", "img": logo, "x": lx, "y": y})
            y += logo.height
            gap(10)

    # ── header: Order # ──
    add_text("Order #{}".format(order.get("order_no", "----")), f_order, lead=2)
    add_hr()

    # ── seat + guest ──
    add_text(_seat_str(order.get("seat")), f_seat, lead=4)
    guest = (order.get("customer_name") or "").strip()
    if guest:
        add_text("Guest: {}".format(guest), f_guest, lead=4)
    add_hr()

    # ── item lines ──
    lines = order.get("lines") or []
    if not lines:
        add_text("(no items)", f_item)
    for line in lines:
        head, addons = _fmt_line(line)
        add_text(head, f_item, lead=2)
        for a in addons:
            add_text("+ {}".format(a), f_addon, indent=int(28 * scale) + 6, lead=2)
        gap(8)

    # ── notes (red) ──
    notes = (order.get("notes") or "").strip()
    if notes:
        note_color = RED if red_enabled else BLACK
        add_hr()
        tri = int(f_note.size * 0.9)
        note_indent = int(tri * 1.15) + int(10 * scale)
        first_y = y
        elements.append({"kind": "triangle", "x": margin, "y": first_y,
                         "size": tri, "color": note_color})
        lh = _line_height(f_note)
        for ln in _wrap(scratch, notes, f_note, content_w - note_indent):
            elements.append({"kind": "text", "text": ln, "font": f_note,
                             "color": note_color, "x": margin + note_indent, "y": y})
            y += lh + int(6 * scale)

    # ── footer ──
    add_hr()
    add_text("kitchen label", f_foot, lead=0)

    content_h = y + margin
    height = fixed_length if fixed_length else max(content_h, int(180 * scale))

    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    for el in elements:
        if el["kind"] == "text":
            draw.text((el["x"], el["y"]), el["text"], font=el["font"],
                      fill=el["color"], anchor="la")
        elif el["kind"] == "hr":
            draw.line([(margin, el["y"]), (width - margin, el["y"])],
                      fill=BLACK, width=max(2, int(3 * scale)))
        elif el["kind"] == "triangle":
            _warning_triangle(draw, el["x"], el["y"], el["size"], el["color"])
        elif el["kind"] == "image":
            img.paste(el["img"], (el["x"], el["y"]))

    return img
