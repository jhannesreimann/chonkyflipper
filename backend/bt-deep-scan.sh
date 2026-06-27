#!/bin/bash
# One-shot bettercap BLE recon for the deep-scan engine. Invoked as root via
# sudo (see the chonky-ops sudoers entry). The duration argument is validated
# to a small integer so this cannot be coerced into running arbitrary
# bettercap commands.

DURATION="${1:-15}"
case "$DURATION" in
    ''|*[!0-9]*) DURATION=15 ;;
esac
[ "$DURATION" -gt 120 ] && DURATION=120

exec timeout "$((DURATION + 10))" bettercap -no-colors \
    -eval "ble.recon on; sleep ${DURATION}; ble.show; quit"
