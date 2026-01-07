#!/bin/bash
set -e

echo "=== Verifying System Hardening ==="

# 1. Install RPM (assumed already copied to /tmp)
rpm -Uvh --force /tmp/chelon-1.0.0-2.fc43.noarch.rpm

# 2. Start Service
systemctl daemon-reload
systemctl restart chelon
sleep 3

# 3. Check Status
if systemctl is-active --quiet chelon; then
    echo "PASS: Service started successfully with hardening."
else
    echo "FAIL: Service failed to start."
    journalctl -u chelon -n 50 --no-pager
    exit 1
fi

# 4. Check Security Score
echo "--- Security Analysis ---"
systemd-analyze security chelon.service --no-pager

# 5. Functional Test (Health Check with mTLS key from previous setup)
# Assuming certs are already in /etc/chelon/certs/ from previous manual setup
# We need CLIENT keys to test. The previous script generated 'client.key' and 'client.crt' in /etc/chelon/certs/ too.
# Let's hope they are there.
echo "--- Functional Test ---"
export CERT_DIR="/etc/chelon/certs"

if [ -f "$CERT_DIR/client.key" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        --cert $CERT_DIR/client.crt --key $CERT_DIR/client.key --cacert $CERT_DIR/ca.crt \
        https://localhost:5050/api/v1/health)
    
    if [ "$HTTP_CODE" == "200" ]; then
        echo "PASS: Health check responded 200 OK."
    else
        echo "FAIL: Health check returned $HTTP_CODE"
        exit 1
    fi
else
    echo "SKIP: Client certs not found for functional test (expected from previous steps)."
fi

echo "=== Verification Complete ==="
