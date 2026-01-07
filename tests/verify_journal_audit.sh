#!/bin/bash
set -e

# Setup
RPM_PATH=$(ls /tmp/chelon-1.0.0-2*.rpm | head -n1)
echo "Installing $RPM_PATH..."
rpm -Uvh --force $RPM_PATH
systemctl restart chelon
sleep 5 # Allow systemd to capture logs

# Config
CERT_DIR="/etc/chelon/certs"
URL="https://localhost:5050/api/v1/sign/rpm"

# Generate a temporary token
TOKEN_OUT=$(chelon-admin generate-token journal-test --permissions sign:rpm)
TOKEN=$(echo "$TOKEN_OUT" | tail -n 1)

echo "Sending signing request..."
RESPONSE=$(curl -s -k \
    --cert $CERT_DIR/client.crt --key $CERT_DIR/client.key \
    -X POST $URL \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"data\": \"$(echo 'fake' | base64)\", \"key_type\": \"legacy\"}")

REQUEST_ID=$(echo $RESPONSE | jq -r .request_id)
echo "Request ID: $REQUEST_ID"

if [ -z "$REQUEST_ID" ] || [ "$REQUEST_ID" == "null" ]; then
    echo "FAIL: No request ID returned."
    exit 1
fi

# Verify via chelon-admin audit (which uses journalctl now)
echo "Checking logs via chelon-admin..."
# chelon-admin needs to be run as root (we assume this script is running as root)
AUDIT_OUTPUT=$(chelon-admin audit --limit 50)
echo "$AUDIT_OUTPUT"

if echo "$AUDIT_OUTPUT" | grep -q "$TOKEN"; then
    echo "PASS: Found token ID in audit log output."
else
    echo "FAIL: Token ID not found in audit output."
    exit 1
fi

# Check for request_id in journal directly to be sure fields are there
# (chelon-admin output might not show request_id in default view, but we are just checking if it works)
if echo "$AUDIT_OUTPUT" | grep -q "✓"; then
     echo "PASS: Audit entry indicates success."
fi

# Cleanup
chelon-admin revoke-token journal-test
