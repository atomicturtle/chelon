#!/bin/bash
set -e

# Setup
RPM_PATH=$(ls /tmp/chelon-1.0.0-2*.rpm | head -n1)
echo "Installing $RPM_PATH..."
rpm -Uvh --force $RPM_PATH
systemctl restart chelon
sleep 3

# Config
CERT_DIR="/etc/chelon/certs"
URL="https://localhost:5050/api/v1/sign/rpm"

# Generate a temporary token if needed (but we probably have one from previous manual setup)
# We need to know a valid token. 
# We'll generate a fresh one to be sure.
TOKEN_OUT=$(chelon-admin generate-token audit-test --permissions sign:rpm)
TOKEN=$(echo "$TOKEN_OUT" | tail -n 1) # Extract token

echo "Generated token: $TOKEN"

# Create fake RPM data (base64)
DATA=$(echo "fake rpm data" | base64)

echo "Sending signing request..."
RESPONSE=$(curl -s -k \
    --cert $CERT_DIR/client.crt --key $CERT_DIR/client.key \
    -X POST $URL \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"data\": \"$DATA\", \"key_type\": \"legacy\"}")

echo "Response: $RESPONSE"

REQUEST_ID=$(echo $RESPONSE | jq -r .request_id)
if [ "$REQUEST_ID" == "null" ] || [ -z "$REQUEST_ID" ]; then
    echo "FAIL: No request_id in response!"
    exit 1
fi

echo "Request ID: $REQUEST_ID"

# Check Audit Log
echo "Checking audit log..."
AUDIT_ENTRY=$(grep "$REQUEST_ID" /var/lib/chelon/audit.log)

if [ -z "$AUDIT_ENTRY" ]; then
    echo "FAIL: Request ID not found in audit log!"
    exit 1
fi

echo "Found Audit Entry: $AUDIT_ENTRY"

# Check for Latency and Payload Size
if [[ "$AUDIT_ENTRY" == *"latency"* ]] && [[ "$AUDIT_ENTRY" == *"payload_size"* ]]; then
    echo "PASS: Audit entry contains latency and payload_size."
else
    echo "FAIL: Audit entry missing latency or payload_size."
    exit 1
fi

# Cleanup
chelon-admin revoke-token audit-test
