#!/bin/bash
# BEEPER KEEPER v2.0 - Dynamic USB Audio Configuration
# Generates ALSA dsnoop configuration for detected USB audio device
# Run this script once at startup before starting camera services

ASOUNDRC="$HOME/.asoundrc"
BACKUP_DIR="$HOME/.config/beeperkeeper"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Find first USB audio capture device
USB_CARD_NAME=""
USB_CARD_NUM=""

while IFS= read -r line; do
    if echo "$line" | grep -qi "USB"; then
        # Extract card number
        card_num=$(echo "$line" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
        # Extract card name (between square brackets)
        card_name=$(echo "$line" | sed -n 's/.*\[\(.*\)\].*/\1/p')

        if [ -n "$card_num" ] && [ -n "$card_name" ]; then
            USB_CARD_NUM="$card_num"
            USB_CARD_NAME="$card_name"
            break
        fi
    fi
done < <(arecord -l 2>/dev/null)

if [ -z "$USB_CARD_NAME" ]; then
    echo "[USB Audio Setup] No USB audio device found" >&2
    exit 1
fi

echo "[USB Audio Setup] Detected: Card $USB_CARD_NUM [$USB_CARD_NAME]" >&2

# Backup existing .asoundrc if it exists
if [ -f "$ASOUNDRC" ]; then
    cp "$ASOUNDRC" "$BACKUP_DIR/asoundrc.backup.$TIMESTAMP"
    echo "[USB Audio Setup] Backed up existing config to $BACKUP_DIR/asoundrc.backup.$TIMESTAMP" >&2
fi

# Generate new ALSA configuration
cat > "$ASOUNDRC" << EOF
# BEEPER KEEPER v2.0 - Generic USB Audio Configuration
# Auto-generated: $(date)
# Detected device: Card $USB_CARD_NUM [$USB_CARD_NAME]
# Uses card NAME instead of number for stability across reboots

# Shared microphone input (dsnoop)
pcm.dsnoop_usb {
    type dsnoop
    ipc_key 5978294
    ipc_perm 0666
    slave {
        pcm "hw:$USB_CARD_NAME"
        channels 1
        rate 16000
        format S16_LE
    }
}

# Shared speaker output (dmix) - MONO for most USB webcams
pcm.dmix_usb {
    type dmix
    ipc_key 5978295
    ipc_perm 0666
    slave {
        pcm "hw:$USB_CARD_NAME"
        channels 1
        rate 48000
        format S16_LE
    }
}

# Asymmetric device (different capture/playback)
pcm.!default {
    type asym
    playback.pcm "dmix_usb"
    capture.pcm "dsnoop_usb"
}

# Explicit names for clarity
pcm.usbspeaker {
    type plug
    slave.pcm "dmix_usb"
}

pcm.usbmic {
    type plug
    slave.pcm "dsnoop_usb"
}

ctl.!default {
    type hw
    card $USB_CARD_NAME
}
EOF

echo "[USB Audio Setup] ✓ Generated $ASOUNDRC" >&2
echo "[USB Audio Setup] ✓ ALSA device 'dsnoop_usb' ready for shared microphone access" >&2

# Test the configuration
if arecord -D dsnoop_usb -d 1 -f S16_LE -r 16000 -c 1 -t raw > /dev/null 2>&1; then
    echo "[USB Audio Setup] ✓ Test recording successful" >&2
else
    echo "[USB Audio Setup] ✗ Test recording failed - check device configuration" >&2
    exit 1
fi

exit 0
