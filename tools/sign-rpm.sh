#!/bin/bash
set -e

RPM_FILE="$1"
CHELON_HOST="${2:-gamera.atomicorp.com}"
CHELON_PORT="${3:-5050}"

if [ -z "$RPM_FILE" ]; then
    echo "Usage: $0 <rpm_file> [chelon_host] [chelon_port]"
    exit 1
fi

if [ ! -f "$RPM_FILE" ]; then
    echo "Error: RPM file not found: $RPM_FILE"
    exit 1
fi

# Check for required tools
for cmd in curl jq rpm gpg base64; do
    if ! command -v $cmd &> /dev/null; then
        echo "Error: Required command '$cmd' not found"
        exit 1
    fi
done

# Check for client certificates
CERT_DIR="${HOME}/.chelon/certs"
if [ ! -f "$CERT_DIR/chelon_client.crt" ] || [ ! -f "$CERT_DIR/chelon_client.key" ] || [ ! -f "$CERT_DIR/chelon_ca.crt" ]; then
    echo "Error: Client certificates not found in $CERT_DIR"
    echo "Expected files: chelon_client.crt, chelon_client.key, chelon_ca.crt"
    exit 1
fi

# Check for token
if [ -z "$CHELON_TOKEN" ]; then
    echo "Error: CHELON_TOKEN environment variable not set"
    echo "Please set it with: export CHELON_TOKEN='your-token-id:secret'"
    exit 1
fi

echo "=== Signing RPM with Chelon ==="
echo "RPM: $RPM_FILE"
echo "Chelon: https://$CHELON_HOST:$CHELON_PORT"
echo ""

# Read and encode the RPM file
echo "Reading RPM file..."
RPM_DATA=$(base64 -w0 "$RPM_FILE")
RPM_SIZE=$(stat -c%s "$RPM_FILE")
echo "RPM size: $RPM_SIZE bytes"
echo "Base64 encoded size: ${#RPM_DATA} bytes"

# Create JSON payload in a temp file
PAYLOAD_FILE=$(mktemp)
cat > "$PAYLOAD_FILE" <<EOF
{"data": "$RPM_DATA", "key_type": "modern"}
EOF

# Send signing request
echo ""
echo "Sending signing request..."
RESPONSE=$(curl -s -k \
    --cert "$CERT_DIR/chelon_client.crt" \
    --key "$CERT_DIR/chelon_client.key" \
    --cacert "$CERT_DIR/chelon_ca.crt" \
    -X POST "https://$CHELON_HOST:$CHELON_PORT/api/v1/sign/rpm" \
    -H "Authorization: Bearer $CHELON_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "@$PAYLOAD_FILE")

# Clean up payload file
rm -f "$PAYLOAD_FILE"

# Check for errors
if echo "$RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
    echo "Error from Chelon service:"
    echo "$RESPONSE" | jq -r '.error'
    exit 1
fi

# Extract signature
echo "Extracting signature..."
SIGNATURE=$(echo "$RESPONSE" | jq -r '.signature')
KEY_ID=$(echo "$RESPONSE" | jq -r '.key_id')
KEY_FP=$(echo "$RESPONSE" | jq -r '.key_fingerprint')
REQUEST_ID=$(echo "$RESPONSE" | jq -r '.request_id')

echo "✓ Signature received"
echo "  Key ID: $KEY_ID"
echo "  Key Fingerprint: $KEY_FP"
echo "  Request ID: $REQUEST_ID"

# Import the signature into RPM
echo ""
echo "Importing signature into RPM..."
SIGNED_RPM="${RPM_FILE%.rpm}.signed.rpm"
cp "$RPM_FILE" "$SIGNED_RPM"

# Write signature to temp file
SIG_FILE=$(mktemp)
echo "$SIGNATURE" > "$SIG_FILE"

# Import signature (this requires the GPG key to be in the local keyring)
echo "Note: Signature import requires GPG key $KEY_ID in local keyring"
echo "Signature saved to: $SIG_FILE"

# Verify the signature
echo ""
echo "Verifying signature..."
rpm -K "$RPM_FILE"

echo ""
echo "=== Summary ==="
echo "Original RPM: $RPM_FILE"
echo "Signature file: $SIG_FILE"
echo "Signed by key: $KEY_FP"
echo ""
echo "To import the public key from Chelon, run:"
echo "  ssh root@$CHELON_HOST 'gpg --export $KEY_ID' | gpg --import"
