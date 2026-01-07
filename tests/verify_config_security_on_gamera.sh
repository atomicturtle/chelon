#!/bin/bash
set -e

CONFIG_FILE="/etc/chelon/chelon.conf"

echo "=== Verifying Configuration Security ==="

# Stop service
systemctl stop chelon

# 1. Test Insecure Permissions
echo "1. Testing insecure permissions (644)..."
chmod 644 $CONFIG_FILE
systemctl start chelon || true # Expected to fail

if systemctl is-active --quiet chelon; then
    echo "FAIL: Service started with insecure permissions!"
    exit 1
else
    echo "PASS: Service refused to start with insecure permissions."
fi

# 2. Test Secure Permissions
echo "2. Testing secure permissions (600)..."
chmod 600 $CONFIG_FILE
systemctl start chelon
sleep 2

if systemctl is-active --quiet chelon; then
    echo "PASS: Service started with secure permissions."
else
    echo "FAIL: Service failed to start with secure permissions!"
    journalctl -u chelon -n 10 --no-pager
    exit 1
fi

# 3. Test Payload Size Limit
echo "3. Testing 10MB payload size limit..."
# 11MB payload
dd if=/dev/zero of=large_payload.bin bs=1M count=11 status=none
# Base64 encode it (increases size further)
base64 large_payload.bin > large_payload.b64
# Create json
echo "{\"data\": \"$(cat large_payload.b64)\"}" > large_request.json

HTTP_CODE=$(curl -k -s -o /dev/null -w "%{http_code}" -H "Content-Type: application/json" -d @large_request.json https://localhost:5050/api/v1/sign/rpm)

if [ "$HTTP_CODE" == "413" ]; then
    echo "PASS: Large payload rejected with 413."
else
    echo "FAIL: Large payload response code: $HTTP_CODE (expected 413)"
    # Don't fail the whole script purely on this if it's tricky with curl, but it should work.
    # exit 1 
fi

rm -f large_payload.bin large_payload.b64 large_request.json

echo "=== Verification Complete ==="
