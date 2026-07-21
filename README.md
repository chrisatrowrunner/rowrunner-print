# rowrunner-print

The 4th piece of the **RowRunner** system: a headless Python worker that runs on a
PC in the venue next to a **Brother QL-820NWB** label printer. It watches the shared
Supabase `orders` table and prints **one food label the instant an order becomes
ready** (`ready_at` fires from the KDS), so the kitchen can stick the label on the bag
for the runner.

RowRunner flow: fan places order → **KDS Confirm** → **KDS Ready** *(this worker prints
here)* → runner claims → runner delivers with a 6-digit code.

The other three apps (fan PWA, runner dispatch, KDS) are separate repos and all share
the same Supabase `orders` table.

---

## What it prints

One label per ready order, big and legible for a grab-and-go bag:

- **Order #<order_no>**
- Seat: `Sec <section> · Row <row> · Seat <seat>`
- `Guest: <customer_name>` (when present)
- Each line: `<qty>× <name> (<option>)` with `+ <addons>` indented
- **⚠ `<notes>` in RED** when the order has notes (two-color roll)

It **never** prints the `code` column — that is hidden by design; the runner gets the
6-digit code from the guest at the seat.

---

## Exactly-once (the important part)

Every `POLL_SECONDS`, the worker queries orders where `ready_at is not null AND
printed_at is null AND stage <= 3` (a delivered order never needs a kitchen label),
oldest ready first. For each row it:

1. **Atomically claims** the row via the `mark_printed(id)` RPC, which sets
   `printed_at = now()` only if it is still null and returns `true` **iff this call won
   the row**.
2. Prints **only when the claim returns `true`** — so exactly one label is produced even
   across restarts or with two workers running at once.
3. On a print **hardware failure after claiming**, logs LOUDLY and calls
   `mark_unprinted(id)` to release the row so it retries on the next poll.

The worker uses the **public anon key only**. Reads are public; both RPCs are
`security definer`. The `service_role` key is deliberately never stored on the venue PC.

---

## One-time setup

### 1. Database (run once)

Open the Supabase SQL editor for this project — **confirm the ref `kboevpucqjoftgmhrkzq`
is in the URL first** (there are other projects in the account):

<https://supabase.com/dashboard/project/kboevpucqjoftgmhrkzq/sql/new>

Paste and run [`supabase/print-rpcs.sql`](supabase/print-rpcs.sql). It creates the
`mark_printed` / `mark_unprinted` RPCs and grants them to `anon`. Idempotent. The
`printed_at` column already exists (it shipped with the KDS migration).

### 2. Python + dependencies

Python **3.11+** recommended (works on 3.9+). On this Mac, Node/Python toolchains aren't
always on PATH — check with `python3 --version`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # Windows: .venv\Scripts\python
```

`brother_ql` is only needed for real printing. For DRY_RUN PNG rendering you only need
`requests`, `Pillow`, `python-dotenv`.

### 3. Config

```bash
cp .env.example .env      # then edit .env
```

Fill in `SUPABASE_ANON_KEY` (the public key the other apps use). Leave `DRY_RUN=1` until
the printer is wired.

---

## Running it

```bash
.venv/bin/python worker.py              # run the poll loop forever
.venv/bin/python worker.py --once       # one poll cycle, then exit
.venv/bin/python worker.py --test-print # send the demo label to the real printer (no DB) — hardware smoke test
.venv/bin/python worker.py --selftest   # render the newest READY real order to out/ (no claim, no print)
.venv/bin/python worker.py --demo       # render a synthetic fully-populated label (shows the red note)
```

`--demo` and `--selftest` are great for eyeballing the label design on the Mac with no
printer and no database writes.

### DRY_RUN

With `DRY_RUN=1`, the worker does everything for real **except** talk to the printer — it
claims the row (`mark_printed`) and writes `out/label-<order_no>.png` instead of printing.
Because it still claims, a DRY_RUN of the live loop marks orders as printed. To preview a
label **without** claiming, use `--selftest` / `--demo`.

---

## The printer (Brother QL-820NWB)

Two-color capable (black + **red**) with a black/red roll. The unit ships with a
**DK-2251** 62mm black/red continuous roll → `LABEL_SIZE=62`, ~696 px printable width.

| stock | `LABEL_SIZE` | notes |
|-------|--------------|-------|
| 62mm continuous, black/red (DK-2251) | `62` | default; ⚠ note prints red |
| 62mm continuous, black only (DK-22205) | `62` | set `LABEL_RED=0` |
| 29×90 die-cut address labels | `29x90` | tighter, fixed-length layout |

### Connectivity — prefer network

The 820NWB is finicky over USB, so use the **network** backend when the PC and printer
are on the same LAN:

```
PRINTER_BACKEND=network
PRINTER_IDENTIFIER=tcp://<printer-ip>:9100
```

Get the printer's IP from its network config sheet (hold the **Cut** button to print it),
and set a static IP or a DHCP reservation so it doesn't move.

**USB fallback:**

```
PRINTER_BACKEND=pyusb
PRINTER_IDENTIFIER=usb://0x04f9:0x<product-id>    # from `brother_ql discover`
```

Brother's USB vendor id is `0x04f9`; the product id isn't hardcoded in brother_ql, so run
`brother_ql discover` to find it.

### Go-live checklist

1. Load a black/red 62mm roll.
2. `pip install -r requirements.txt` (installs `brother_ql`).
3. Set `PRINTER_BACKEND` / `PRINTER_IDENTIFIER` in `.env` for your printer.
4. **Hardware smoke test:** `python worker.py --test-print` → a demo label prints. This
   needs no database, so it isolates "is the printer working?" from everything else.
5. Run the SQL (setup step 1) to create the RPCs.
6. Set `DRY_RUN=0`, then `python worker.py --once` and tap **Mark ready** on a test order
   in the KDS — watch it print.
7. Switch to the always-on loop (below).

---

## Keeping it running on the venue PC

**Windows (Task Scheduler):** create a task "At log on" / "At startup" that runs
`C:\path\to\.venv\Scripts\python.exe C:\path\to\worker.py`, set to restart on failure.

**macOS (launchd) / Linux (systemd):** a user service that runs `worker.py` with
`Restart=always`. The worker logs to stdout with timestamps.

---

## Troubleshooting

- **Reads fail with a network/DNS error:** the shared Supabase project is free-tier and
  auto-pauses after ~7 idle days. Resume it in the dashboard.
- **`Could not find the function public.mark_printed`:** you haven't run
  `supabase/print-rpcs.sql` yet (step 1).
- **`brother_ql is not installed`:** `pip install -r requirements.txt`, or set `DRY_RUN=1`.
- **Nothing prints but orders are ready:** check they're `stage <= 3` (delivered orders
  are skipped) and `printed_at is null`. A row already printed won't reprint — that's the
  exactly-once guarantee. To force a reprint, clear its `printed_at` in the dashboard.
- **Printer unreachable:** confirm the IP, that the PC and printer share a LAN, and that
  port 9100 is open. The worker logs loudly and releases the row for retry.
