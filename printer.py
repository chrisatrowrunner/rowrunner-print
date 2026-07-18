"""Send a rendered label to the Brother QL-820NWB — or, in DRY_RUN, save a PNG.

brother_ql is imported lazily so the whole worker is installable and testable on
a machine with no printer (and without brother_ql) as long as DRY_RUN=1.
"""
import os


class PrintError(Exception):
    """Raised on any hardware/network failure while printing (after claiming a row)."""


def save_png(img, out_dir, order_no):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "label-{}.png".format(order_no))
    img.save(path)
    return path


def print_label(img, *, model, backend, identifier, label_size, red):
    """Raster `img` and send it to the printer. Raises PrintError on any failure."""
    try:
        from brother_ql.conversion import convert
        from brother_ql.backends.helpers import send
        from brother_ql.raster import BrotherQLRaster
    except ImportError as e:
        raise PrintError(
            "brother_ql is not installed — `pip install brother_ql` "
            "(or set DRY_RUN=1 to render PNGs instead). Detail: {}".format(e)
        )

    try:
        qlr = BrotherQLRaster(model)
        qlr.exception_on_warning = True
        instructions = convert(
            qlr=qlr,
            images=[img],           # PIL image
            label=str(label_size),  # "62" or "29x90"
            rotate="auto",
            threshold=70.0,
            dither=False,
            compress=False,
            red=bool(red),          # two-color: draw ⚠ note red
            dpi_600=False,
            hq=True,
            cut=True,
        )
    except Exception as e:
        raise PrintError("failed to rasterize label: {}".format(e))

    try:
        send(
            instructions=instructions,
            printer_identifier=identifier,
            backend_identifier=backend,
            blocking=True,
        )
    except Exception as e:
        # network unreachable, USB not found, printer offline/out of labels, etc.
        raise PrintError(
            "printer send failed (backend={}, id={}): {}".format(backend, identifier, e)
        )
