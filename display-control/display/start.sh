#!/bin/bash
set -e

# Print info
echo "Starting Display Client"
echo "Display ID: $DISPLAY_ID"
echo "Default URL: $DEFAULT_URL"

# Make sure DISPLAY is set if not provided
if [ -z "$DISPLAY" ]; then
  export DISPLAY=${DISPLAY_ID:-:0}
  echo "Setting DISPLAY to $DISPLAY"
fi

# Start X server
echo "Starting X server on $DISPLAY"
Xorg $DISPLAY -s 0 -dpms -ac -nolisten tcp &
sleep 3

# Start window manager
echo "Starting window manager"
openbox-session &
sleep 3

# Verify X server is running
echo "Verifying X server"
if ! DISPLAY=$DISPLAY xset q &>/dev/null; then
  echo "X server not running properly. Trying again..."
  sleep 5
  if ! DISPLAY=$DISPLAY xset q &>/dev/null; then
    echo "ERROR: X server failed to start!"
  fi
fi

# Detect screen resolution 
echo "Detecting screen resolution..."
xrandr_output=$(DISPLAY=$DISPLAY xrandr 2>/dev/null | grep -w "connected" | grep -o '[0-9]*x[0-9]*+[0-9]*+[0-9]*' | head -1)
if [ -n "$xrandr_output" ]; then
  # Extract resolution from something like "1920x1080+0+0"
  resolution=$(echo "$xrandr_output" | cut -d'+' -f1)
  echo "Detected resolution: $resolution"
  export DETECTED_RESOLUTION="$resolution"
else
  echo "Could not detect resolution, using default"
  export DETECTED_RESOLUTION="1024x768"
fi

# Start the display client
echo "Starting display client"
cd /app
python3 display.py