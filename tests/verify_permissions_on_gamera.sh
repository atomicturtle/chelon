#!/bin/bash
set -e

CONFIG_FILE="/etc/chelon/chelon.conf"
DATA_DIR="/var/lib/chelon"

echo "=== Verifying File Permissions ==="

# 1. Check Config File Permissions
# stat -c "%a %U %G" file
PERM=$(stat -c "%a %U %G" $CONFIG_FILE)
if [ "$PERM" == "600 chelon chelon" ]; then
    echo "PASS: Config file permissions are $PERM"
else
    echo "FAIL: Config file permissions are $PERM (Expected: 600 chelon chelon)"
    exit 1
fi

# 2. Check Data Dir Permissions
PERM=$(stat -c "%a %U %G" $DATA_DIR)
if [ "$PERM" == "750 chelon chelon" ]; then
    echo "PASS: Data dir permissions are $PERM"
else
    echo "FAIL: Data dir permissions are $PERM (Expected: 750 chelon chelon)"
    exit 1
fi

echo "=== Verifying Service Startup ==="
systemctl restart chelon
sleep 2
if systemctl is-active --quiet chelon; then
    echo "PASS: Service started successfully."
else
    echo "FAIL: Service failed to start."
    journalctl -u chelon -n 20 --no-pager
    exit 1
fi

echo "=== Verification Complete ==="
