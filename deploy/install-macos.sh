#!/bin/bash
# Install the RowRunner print worker as a launchd service on macOS:
# starts automatically at login and restarts itself if it ever crashes.
#
#   bash deploy/install-macos.sh
#
# Re-run it any time to reinstall. To stop/remove, see the printed commands.
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"      # project root
PY="$DIR/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.rowrunner.print.plist"

if [ ! -x "$PY" ]; then
  echo "!! No venv found at $PY"
  echo "!! Create it first:  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.rowrunner.print</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$DIR/worker.py</string>
    </array>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$DIR/worker.log</string>
    <key>StandardErrorPath</key><string>$DIR/worker.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

echo "Installed and started."
echo "  Logs:   tail -f $DIR/worker.log"
echo "  Status: launchctl list | grep rowrunner"
echo "  Stop:   launchctl unload $PLIST"
echo "  Start:  launchctl load -w $PLIST"
