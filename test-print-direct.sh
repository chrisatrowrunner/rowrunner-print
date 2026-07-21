#!/bin/bash
# RowRunner — hardware test print over the printer's Wireless Direct hotspot.
#
# Run this AFTER you've joined your Mac's Wi-Fi to the DIRECT-...-QL-820NWB
# network (password: rowrunner). It needs NO internet — everything is local.
#
#   bash test-print-direct.sh
#
# In Wireless Direct mode the printer IS this Mac's network gateway, so we find
# it automatically. Fallback is Brother's Wireless Direct default (192.168.118.1).

cd "$(dirname "$0")" || exit 1
echo "=== RowRunner hardware test print (Wireless Direct) ==="

GW=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')
CANDIDATES="$GW 192.168.118.1"

PRINTER=""
for ip in $CANDIDATES; do
  [ -z "$ip" ] && continue
  if (echo > "/dev/tcp/$ip/9100") 2>/dev/null; then
    PRINTER="$ip"
    break
  fi
done

if [ -z "$PRINTER" ]; then
  echo
  echo "!! Couldn't reach the printer on port 9100 (tried: $CANDIDATES )."
  echo "!! Check that your Mac's Wi-Fi is joined to the DIRECT-...-QL-820NWB"
  echo "!! network (top-right Wi-Fi icon). 'Connected, no internet' is CORRECT."
  echo "!! Then run this again."
  exit 1
fi

echo "Found the printer at $PRINTER:9100 — sending the test label now..."
echo
PRINTER_BACKEND=network PRINTER_IDENTIFIER="tcp://$PRINTER:9100" DRY_RUN=0 \
  .venv/bin/python worker.py --test-print

echo
echo "=== done. If a label came out, the hardware works! ==="
echo "Now switch your Wi-Fi back to your home network and tell Claude what happened."
