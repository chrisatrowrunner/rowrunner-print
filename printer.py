"""Send a rendered label to the Brother QL-820NWB — or, in DRY_RUN, save a PNG.

brother_ql is imported lazily so the whole worker is installable and testable on
a machine with no printer (and without brother_ql) as long as DRY_RUN=1.
"""
import os
import socket
from concurrent.futures import ThreadPoolExecutor


class PrintError(Exception):
    """Raised on any hardware/network failure while printing (after claiming a row)."""


# ── printer discovery ────────────────────────────────────────────────────────
# The printer's IP can change (DHCP). We try the configured address first, and
# if it's unreachable we scan the local network for whatever is listening on the
# printer's raster port (9100) — so a moved printer heals itself, no config edit.

def _port_open(ip, port, timeout=0.3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _local_ipv4():
    """This machine's primary LAN IPv4 (no traffic actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _parse_tcp(identifier):
    """'tcp://10.0.0.36:9100' -> ('10.0.0.36', 9100)."""
    body = identifier.split("://", 1)[-1]
    host, _, port = body.partition(":")
    return host, (int(port) if port else 9100)


def find_printer(configured_identifier, backend, log=print):
    """Return a reachable 'tcp://ip:port' for the printer.

    Non-network backends (e.g. pyusb) are returned unchanged. For the network
    backend: use the configured address if it answers on the printer port;
    otherwise scan the local /24 and return the first host that does. Falls back
    to the configured identifier if nothing is found (so errors stay meaningful).
    """
    if backend != "network" or "://" not in configured_identifier:
        return configured_identifier

    host, port = _parse_tcp(configured_identifier)
    if host and _port_open(host, port):
        return configured_identifier

    local = _local_ipv4()
    if not local:
        return configured_identifier
    prefix = local.rsplit(".", 1)[0]
    candidates = ["{}.{}".format(prefix, i) for i in range(1, 255)
                  if "{}.{}".format(prefix, i) != local]
    with ThreadPoolExecutor(max_workers=64) as ex:
        hits = [ip for ip, ok in
                zip(candidates, ex.map(lambda ip: _port_open(ip, port, 0.25), candidates))
                if ok]
    if hits:
        found = "tcp://{}:{}".format(hits[0], port)
        log("printer not reachable at {} — auto-discovered on the network at {}"
            .format(configured_identifier, found))
        if len(hits) > 1:
            log("(note: {} devices answered on port {}; using the first: {})"
                .format(len(hits), port, hits[0]))
        return found
    return configured_identifier


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
