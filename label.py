"""Render a RowRunner food label as a Pillow image.

Black text on white; the ⚠ note (if any) is drawn in pure red so brother_ql's
two-color conversion (red=True) prints it on the red channel of a black/red roll.

NEVER render the `code` column — it is hidden by design and the runner must get
the 6-digit code from the guest.

Two label stocks are supported (selected by LABEL_SIZE in .env):
  "62"    → 62mm continuous, 696 px printable width, variable length.
  "29x90" → 29x90 die-cut, 306 px wide × 991 px long, tighter layout.
"""
from PIL import Image, ImageDraw, ImageFont

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)  # pure red so brother_ql detects it for the red channel

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
    # Last resort: bitmap default (ugly, but the worker still produces a label).
    return ImageFont.load_default()


def _text_size(draw, text, font):
    # textbbox is stable across Pillow versions; returns (l, t, r, b).
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return (r - l, b - t)


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap; hard-splits any single word too wide for the label."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_size(draw, trial, font)[0] <= max_width or not cur:
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
    seat = seat or {}
    section = seat.get("section", "?")
    row = seat.get("row", "?")
    s = seat.get("seat", "?")
    return "Sec {} · Row {} · Seat {}".format(section, row, s)


def _warning_triangle(draw, x, y, size, color):
    """Draw a hollow warning triangle with a '!' — a reliable stand-in for ⚠️."""
    h = size
    w = int(size * 1.15)
    top = (x + w / 2, y)
    left = (x, y + h)
    right = (x + w, y + h)
    lw = max(2, size // 12)
    draw.line([top, left, right, top], fill=color, width=lw, joint="curve")
    # exclamation
    ex = x + w / 2
    draw.line([(ex, y + h * 0.32), (ex, y + h * 0.66)], fill=color, width=lw)
    r = max(2, lw)
    draw.ellipse([ex - r, y + h * 0.74, ex + r, y + h * 0.74 + 2 * r], fill=color)
    return w


def render_label(order, label_size="62", red_enabled=True,
                 font_bold_path="", font_regular_path=""):
    """Build and return an RGB Pillow image for one order row."""
    spec = LABEL_SPECS.get(str(label_size), LABEL_SPECS["62"])
    width = spec["width"]
    fixed_length = spec["length"]

    # Scale type to the label width (696 px is the reference design).
    scale = width / 696.0
    margin = max(10, int(24 * scale))
    content_w = width - 2 * margin

    def B(px):  # bold font at a scaled size
        return _font(max(9, int(px * scale)), True, font_bold_path)

    def R(px):  # regular font
        return _font(max(9, int(px * scale)), False, font_regular_path)

    f_order = B(70)
    f_seat = B(40)
    f_guest = R(34)
    f_item = B(38)
    f_addon = R(30)
    f_note = B(40)
    f_foot = R(24)

    # Measure on a scratch canvas, laying out an element list we replay when we
    # know the final height.
    scratch = ImageDraw.Draw(Image.new("RGB", (width, 10), WHITE))
    elements = []  # each: dict(kind=..., ...)
    y = margin

    def gap(px):
        nonlocal y
        y += max(4, int(px * scale))

    def add_text(text, font, color=BLACK, indent=0, min_gap=6):
        nonlocal y
        for ln in _wrap(scratch, text, font, content_w - indent):
            h = _text_size(scratch, ln, font)[1]
            elements.append({"kind": "text", "text": ln, "font": font,
                             "color": color, "x": margin + indent, "y": y})
            y += h + int(min_gap * scale)

    def add_hr():
        nonlocal y
        gap(6)
        elements.append({"kind": "hr", "y": y})
        y += max(2, int(3 * scale))
        gap(8)

    # ── header: Order # ──
    add_text("Order #{}".format(order.get("order_no", "----")), f_order, min_gap=2)
    add_hr()

    # ── seat ──
    add_text(_seat_str(order.get("seat")), f_seat, min_gap=4)

    # ── guest (only if present) ──
    guest = (order.get("customer_name") or "").strip()
    if guest:
        add_text("Guest: {}".format(guest), f_guest, min_gap=4)

    add_hr()

    # ── item lines ──
    lines = order.get("lines") or []
    if not lines:
        add_text("(no items)", f_item)
    for line in lines:
        head, addons = _fmt_line(line)
        add_text(head, f_item, min_gap=2)
        for a in addons:
            add_text("+ {}".format(a), f_addon, indent=int(28 * scale) + 6, min_gap=2)
        gap(6)

    # ── notes (red) ──
    notes = (order.get("notes") or "").strip()
    note_color = RED if (notes and red_enabled) else BLACK
    if notes:
        add_hr()
        tri = int(f_note.size * 0.9)
        elements.append({"kind": "triangle", "x": margin, "y": y,
                         "size": tri, "color": note_color})
        note_indent = int(tri * 1.15) + int(10 * scale)
        note_start_y = y
        for i, ln in enumerate(_wrap(scratch, notes, f_note, content_w - note_indent)):
            h = _text_size(scratch, ln, f_note)[1]
            yy = note_start_y if i == 0 else y
            elements.append({"kind": "text", "text": ln, "font": f_note,
                             "color": note_color, "x": margin + note_indent, "y": yy})
            y = yy + h + int(6 * scale)

    # ── footer ──
    gap(6)
    add_hr()
    add_text("RowRunner · kitchen label", f_foot, min_gap=0)

    content_h = y + margin

    # Final canvas: continuous grows to content; die-cut is a fixed length.
    if fixed_length:
        height = fixed_length
    else:
        height = max(content_h, int(180 * scale))

    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    for el in elements:
        if el["kind"] == "text":
            draw.text((el["x"], el["y"]), el["text"], font=el["font"], fill=el["color"])
        elif el["kind"] == "hr":
            draw.line([(margin, el["y"]), (width - margin, el["y"])],
                      fill=BLACK, width=max(2, int(3 * scale)))
        elif el["kind"] == "triangle":
            _warning_triangle(draw, el["x"], el["y"], el["size"], el["color"])

    return img
