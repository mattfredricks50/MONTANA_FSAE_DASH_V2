#!/bin/bash
# Race Dash startup script for Raspberry Pi
# Install: add to /etc/rc.local (before "exit 0") or use a systemd service
#
# rc.local method:
#   cd /home/pi/dash && ./start_dash.sh &
#
# systemd method (recommended):
#   sudo cp racedash.service /etc/systemd/system/
#   sudo systemctl enable racedash
#   sudo systemctl start racedash

DASH_DIR="/home/pi/dash"
LOG_FILE="/home/pi/dash/dash.log"

# ── Wait for display ──────────────────────────────────────
# HDMI/framebuffer may not be ready immediately on boot
sleep 2

# ── Performance ───────────────────────────────────────────
# Lock CPU to max frequency (no thermal throttling hesitation)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>&1

# ── Display settings ──────────────────────────────────────
# Disable screen blanking / power saving (prevents display going black)
export DISPLAY=:0
xset -dpms 2>/dev/null
xset s off 2>/dev/null

# Hide mouse cursor (no cursor visible on touchscreen)
unclutter -idle 0 -root 2>/dev/null &

# ── Environment ───────────────────────────────────────────
cd "$DASH_DIR"
export PYTHONUNBUFFERED=1
# Don't set SDL_VIDEODRIVER here — the app auto-detects (kmsdrm → fbcon fallback)
export SDL_NOMOUSE=1

# ── Launch with auto-restart ──────────────────────────────
# If the dash crashes, wait 3 seconds and relaunch.
# Logs stdout/stderr to dash.log (keeps last 2 copies).
while true; do
    echo "========================================" >> "$LOG_FILE"
    echo "Dash starting: $(date)" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"

    python3 race_dash_pygame.py >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?

    echo "Dash exited with code $EXIT_CODE at $(date)" >> "$LOG_FILE"

    # Exit code 0 = clean shutdown (user pressed Escape), don't restart
    if [ $EXIT_CODE -eq 0 ]; then
        echo "Clean exit, not restarting." >> "$LOG_FILE"
        break
    fi

    # Rotate log if it gets big (keep it under 1MB)
    if [ -f "$LOG_FILE" ] && [ $(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null) -gt 1000000 ]; then
        mv "$LOG_FILE" "${LOG_FILE}.old"
    fi

    echo "Restarting in 3 seconds..." >> "$LOG_FILE"
    sleep 3
done
