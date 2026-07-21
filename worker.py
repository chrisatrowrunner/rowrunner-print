#!/usr/bin/env python3
"""RowRunner label print worker.

Watches the shared Supabase `orders` table and prints ONE food label the instant
an order becomes ready (ready_at fires from the KDS), so the kitchen can stick it
on the bag for the runner.

Exactly-once, even across restarts or two workers running at once:
  1. poll rows where ready_at is set, printed_at is null, stage <= MAX_PRINT_STAGE
  2. ATOMICALLY claim each via the mark_printed(id) RPC (sets printed_at=now() only
     if still null; returns true iff THIS call won the row)
  3. print only when the claim returns true
  4. on a print HARDWARE failure after claiming, log LOUDLY and mark_unprinted(id)
     to release the row for a later retry.

Auth: PUBLIC anon key only. Reads are public; both RPCs are security-definer.

Usage:
  python worker.py             # run the poll loop forever
  python worker.py --once      # one poll cycle, then exit
  python worker.py --test-print# send the demo label to the real printer (no DB) — hardware smoke test
  python worker.py --selftest  # render the newest READY real order to out/ (no claim, no print)
  python worker.py --demo      # render a synthetic fully-populated label (shows the red note)
"""
import sys
import time
import signal

import requests

import config
from label import render_label
from printer import print_label, save_png, PrintError

# Columns to read. NEVER include `code` (hidden by design).
COLS = "id,order_no,seat,stand,lines,customer_name,notes,stage,ready_at,printed_at"

_running = True


def log(msg):
    # flush so logs appear immediately when run under a service manager
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


def _headers():
    return {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": "Bearer " + config.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }


def fetch_ready_orders():
    """Return rows ready to print, oldest ready first."""
    params = {
        "select": COLS,
        "ready_at": "not.is.null",
        "printed_at": "is.null",
        "stage": "lte.{}".format(config.MAX_PRINT_STAGE),
        "order": "ready_at.asc",
    }
    r = requests.get(
        config.SUPABASE_URL + "/rest/v1/orders",
        headers=_headers(), params=params, timeout=15,
    )
    r.raise_for_status()
    return r.json()


def mark_printed(order_id):
    """Atomic claim. Returns True iff this call won the row (printed_at was null)."""
    r = requests.post(
        config.SUPABASE_URL + "/rest/v1/rpc/mark_printed",
        headers=_headers(), json={"p_id": order_id}, timeout=15,
    )
    r.raise_for_status()
    return r.json() is True


def mark_unprinted(order_id):
    """Release a claimed row after a hardware failure so it can retry."""
    r = requests.post(
        config.SUPABASE_URL + "/rest/v1/rpc/mark_unprinted",
        headers=_headers(), json={"p_id": order_id}, timeout=15,
    )
    r.raise_for_status()


def handle_order(order):
    """Claim → render → print one order. Assumes it passed the fetch filter."""
    oid = order["id"]
    ono = order.get("order_no", "----")

    # 1) atomic claim
    try:
        won = mark_printed(oid)
    except requests.RequestException as e:
        log("! claim RPC failed for #{} — will retry next poll: {}".format(ono, e))
        return
    if not won:
        # another worker (or an earlier cycle) already claimed it. Not an error.
        return

    # 2) render
    img = render_label(
        order,
        label_size=config.LABEL_SIZE,
        red_enabled=config.LABEL_RED,
        font_bold_path=config.FONT_BOLD,
        font_regular_path=config.FONT_REGULAR,
    )

    # 3) print (or, in DRY_RUN, save a PNG)
    if config.DRY_RUN:
        path = save_png(img, config.OUT_DIR, ono)
        log("DRY_RUN: claimed & rendered #{} -> {}".format(ono, path))
        return

    try:
        print_label(
            img,
            model=config.PRINTER_MODEL,
            backend=config.PRINTER_BACKEND,
            identifier=config.PRINTER_IDENTIFIER,
            label_size=config.LABEL_SIZE,
            red=config.LABEL_RED,
        )
        log("printed #{}".format(ono))
    except PrintError as e:
        # LOUD: we claimed the row but the hardware failed. Release it for retry.
        log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        log("!! PRINT FAILED for order #{} — {}".format(ono, e))
        log("!! releasing the row (mark_unprinted) so it retries next poll.")
        log("!! Check the printer: powered on? label roll loaded? reachable?")
        log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        try:
            mark_unprinted(oid)
        except requests.RequestException as e2:
            log("!! ALSO failed to release #{} — it will NOT reprint until "
                "printed_at is cleared manually: {}".format(ono, e2))


def poll_once():
    try:
        orders = fetch_ready_orders()
    except requests.RequestException as e:
        # Free-tier Supabase auto-pauses after ~7 idle days → DNS/network error here.
        log("! read failed (network/DNS?). If the project is paused, resume it in "
            "the Supabase dashboard. Detail: {}".format(e))
        return
    for order in orders:
        if not _running:
            break
        handle_order(order)


def run_loop():
    gaps = config.missing()
    if gaps:
        log("FATAL: missing required settings: {}. Copy .env.example to .env and "
            "fill them in.".format(", ".join(gaps)))
        sys.exit(1)

    mode = "DRY_RUN (PNG only)" if config.DRY_RUN else "LIVE ({} via {})".format(
        config.PRINTER_MODEL, config.PRINTER_BACKEND)
    log("RowRunner print worker starting — {}, label={}, poll={}s".format(
        mode, config.LABEL_SIZE, config.POLL_SECONDS))
    log("watching {} for ready, unprinted orders (stage <= {})".format(
        config.SUPABASE_URL, config.MAX_PRINT_STAGE))

    while _running:
        poll_once()
        # sleep in small slices so Ctrl-C / SIGTERM is responsive
        for _ in range(max(1, config.POLL_SECONDS)):
            if not _running:
                break
            time.sleep(1)
    log("stopped.")


# ── demo / selftest (no claim, no print — just render a PNG to eyeball) ──────
_DEMO_ORDER = {
    "order_no": 4845,
    "seat": {"section": "204", "row": "J", "seat": "17"},
    "stand": {"name": "Liberty Bites", "loc": "Concourse C · Sec 232"},
    "customer_name": "Chris D.",
    "lines": [
        {"qty": 2, "name": "Classic Hot Dog", "option": "Everything",
         "addons": ["Extra onions", "Side of chili"]},
        {"qty": 1, "name": "Kettle Popcorn", "option": "Large", "addons": []},
        {"qty": 1, "name": "Craft Lemonade", "option": "No ice", "addons": []},
    ],
    "notes": "Severe peanut allergy — keep away from nuts!",
}


def render_demo():
    img = render_label(_DEMO_ORDER, label_size=config.LABEL_SIZE,
                       red_enabled=config.LABEL_RED,
                       font_bold_path=config.FONT_BOLD,
                       font_regular_path=config.FONT_REGULAR)
    path = save_png(img, config.OUT_DIR, "DEMO-4845")
    log("demo label rendered -> {} ({}x{})".format(path, img.width, img.height))


def render_selftest():
    """Fetch the newest READY real order and render it — no claim, no print."""
    if config.missing():
        log("FATAL: set SUPABASE_URL and SUPABASE_ANON_KEY in .env first.")
        sys.exit(1)
    params = {"select": COLS, "ready_at": "not.is.null",
              "order": "ready_at.desc", "limit": "1"}
    r = requests.get(config.SUPABASE_URL + "/rest/v1/orders",
                     headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        log("no orders with ready_at set found. Tap 'Mark ready' in the KDS, or "
            "use --demo for a synthetic label.")
        return
    order = rows[0]
    img = render_label(order, label_size=config.LABEL_SIZE,
                       red_enabled=config.LABEL_RED,
                       font_bold_path=config.FONT_BOLD,
                       font_regular_path=config.FONT_REGULAR)
    path = save_png(img, config.OUT_DIR, order.get("order_no", "selftest"))
    log("selftest: rendered real order #{} -> {} ({}x{}) [NOT claimed, NOT "
        "printed]".format(order.get("order_no"), path, img.width, img.height))


def test_print():
    """Render the demo label and send it to the CONFIGURED printer — no DB, no claim.

    A hardware smoke test: proves the printer, roll, and connection work before you
    wire up the database side. Ignores DRY_RUN (its whole purpose is to hit the printer).
    """
    img = render_label(_DEMO_ORDER, label_size=config.LABEL_SIZE,
                       red_enabled=config.LABEL_RED,
                       font_bold_path=config.FONT_BOLD,
                       font_regular_path=config.FONT_REGULAR)
    save_png(img, config.OUT_DIR, "TEST-PRINT")  # also keep a copy to compare against
    log("test-print: sending demo label to {} via {} ({})...".format(
        config.PRINTER_MODEL, config.PRINTER_BACKEND, config.PRINTER_IDENTIFIER))
    try:
        print_label(img, model=config.PRINTER_MODEL, backend=config.PRINTER_BACKEND,
                    identifier=config.PRINTER_IDENTIFIER, label_size=config.LABEL_SIZE,
                    red=config.LABEL_RED)
        log("test-print: OK — a label should have come out. If it did, the hardware "
            "is good; set DRY_RUN=0 and run the loop.")
    except PrintError as e:
        log("!! test-print FAILED: {}".format(e))
        log("!! checklist: printer powered on? label roll loaded? "
            "PRINTER_BACKEND/PRINTER_IDENTIFIER correct in .env? "
            "(network: PC + printer on same Wi-Fi, port 9100; USB: run `brother_ql discover`)")
        sys.exit(1)


def _stop(*_a):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    args = set(sys.argv[1:])
    if "--demo" in args:
        render_demo()
    elif "--test-print" in args:
        test_print()
    elif "--selftest" in args:
        render_selftest()
    elif "--once" in args:
        if config.missing():
            log("FATAL: set SUPABASE_URL and SUPABASE_ANON_KEY in .env first.")
            sys.exit(1)
        poll_once()
    else:
        run_loop()


if __name__ == "__main__":
    main()
