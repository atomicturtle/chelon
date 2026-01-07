# Chelon Usage Guide

## Overview

This guide covers how to use Chelon to sign RPM packages and repository metadata.

---

## Signing Methods

Chelon provides three ways to sign packages:

1. **Python Client Library** - Programmatic signing
2. **Command-Line Tools** - `chelon-sign-rpm`, `chelon-sign-repomd`
3. **Direct API Calls** - Using curl or similar

---

## Method 1: Command-Line Tools (Recommended)

### Setup

```bash
# Install client tools
sudo dnf install chelon-client

# Configure environment
export CHELON_URL="https://gamera:5050"
export CHELON_TOKEN="your-token-id:secret"
export CHELON_CERT_DIR="$HOME/.chelon/certs"

# Copy client certificates
mkdir -p ~/.chelon/certs
scp /etc/chelon/certs/chelon_client.* ~/.chelon/certs/
scp /etc/chelon/certs/chelon_ca.crt ~/.chelon/certs/
```

### Sign an RPM

```bash
# Sign a single RPM (detached signature)
chelon-sign-rpm package.rpm

# Embed signature into RPM header (Integrated Signing)
# This allows 'rpm -K' to work natively
chelon-sign-rpm --resign package.rpm

# Specify key type
chelon-sign-rpm --key-type legacy package.rpm

# Sign multiple RPMs
for rpm in *.rpm; do
    chelon-sign-rpm "$rpm"
done
```

**Output:**
```
=== Signing RPM with Chelon ===
RPM: package.rpm
Chelon: https://gamera:5050

Reading RPM file...
RPM size: 1234567 bytes

Sending signing request...
✓ Signature received
  Key ID: CB2C73F04F3BE076
  Key Fingerprint: 1234567890ABCDEF...
  Request ID: abc-123-def

Signature saved to: /tmp/tmp.xyz123
```

### Sign Repository Metadata

```bash
# Sign repomd.xml
chelon-sign-repomd repodata/repomd.xml

# Specify key type
chelon-sign-repomd --key-type modern repodata/repomd.xml
```

**Output:**
```
=== Signing Repository Metadata ===
File: repodata/repomd.xml
Chelon: https://gamera:5050

Reading metadata file...
File size: 12345 bytes

Sending signing request...
✓ Signature received
  Key ID: CB2C73F04F3BE076
  Request ID: xyz-789-abc

Signature saved to: repodata/repomd.xml.asc
```

---

## Method 2: Python Client Library

### Basic Usage

```python
from chelon_client import ChelonClient

# Initialize client
client = ChelonClient(
    url="https://gamera:5050",
    token="your-token-id:secret",
    cert_dir="/path/to/certs"
)

# Sign a file
response = client.sign_file(
    file_path="package.rpm",
    key_type="modern",
    operation="rpm"
)

print(f"Signature: {response['signature']}")
print(f"Key ID: {response['key_id']}")
print(f"Request ID: {response['request_id']}")
```

### Sign Data in Memory

```python
# Sign arbitrary data
data = b"some data to sign"
response = client.sign_data(
    data=data,
    key_type="modern",
    operation="rpm"
)

# Save signature
with open("signature.asc", "w") as f:
    f.write(response['signature'])
```

### Error Handling

```python
from chelon_client import ChelonClient, ChelonClientError

try:
    client = ChelonClient()
    response = client.sign_file("package.rpm")
except ChelonClientError as e:
    print(f"Signing failed: {e}")
    sys.exit(1)
```

---

## Method 3: Direct API Calls

### Sign RPM via API

```bash
# Prepare data
RPM_DATA=$(base64 -w0 package.rpm)

# Call API
curl -k -X POST https://gamera:5050/api/v1/sign/rpm \
  --cert ~/.chelon/certs/chelon_client.crt \
  --key ~/.chelon/certs/chelon_client.key \
  --cacert ~/.chelon/certs/chelon_ca.crt \
  -H "Authorization: Bearer your-token-id:secret" \
  -H "Content-Type: application/json" \
  -d "{
    \"data\": \"$RPM_DATA\",
    \"key_type\": \"modern\"
  }"
```

### Sign Repository Metadata via API

```bash
# Prepare data
REPOMD_DATA=$(base64 -w0 repodata/repomd.xml)

# Call API
curl -k -X POST https://gamera:5050/api/v1/sign/repodata \
  --cert ~/.chelon/certs/chelon_client.crt \
  --key ~/.chelon/certs/chelon_client.key \
  --cacert ~/.chelon/certs/chelon_ca.crt \
  -H "Authorization: Bearer your-token-id:secret" \
  -H "Content-Type: application/json" \
  -d "{
    \"data\": \"$REPOMD_DATA\",
    \"key_type\": \"legacy\"
  }"
```

### API Response

```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----",
  "key_id": "CB2C73F04F3BE076",
  "key_fingerprint": "1234567890ABCDEF...",
  "request_id": "abc-123-def-456",
  "timestamp": "2026-01-07T15:30:00Z"
}
```

---

## Integration with Build Scripts

### GitLab CI Example

```yaml
sign_packages:
  stage: sign
  script:
    - export CHELON_URL="https://gamera:5050"
    - export CHELON_TOKEN="$CHELON_TOKEN"  # From CI/CD secrets
    - export CHELON_CERT_DIR="/builds/.chelon/certs"
    
    # Sign all RPMs
    - for rpm in dist/*.rpm; do
        chelon-sign-rpm "$rpm"
      done
    
    # Sign repository metadata
    - chelon-sign-repomd dist/repodata/repomd.xml
```

### Makefile Example

```makefile
RPMS := $(wildcard dist/*.rpm)

sign: $(RPMS)
	@for rpm in $(RPMS); do \
		echo "Signing $$rpm..."; \
		chelon-sign-rpm $$rpm || exit 1; \
	done
	@echo "Signing repository metadata..."
	@chelon-sign-repomd dist/repodata/repomd.xml

.PHONY: sign
```

### Shell Script Example

```bash
#!/bin/bash
set -e

CHELON_URL="${CHELON_URL:-https://gamera:5050}"
CHELON_TOKEN="${CHELON_TOKEN:?CHELON_TOKEN not set}"

# Sign all RPMs in directory
for rpm in "$1"/*.rpm; do
    echo "Signing: $rpm"
    chelon-sign-rpm "$rpm"
done

# Sign repository metadata
if [ -f "$1/repodata/repomd.xml" ]; then
    echo "Signing repository metadata"
    chelon-sign-repomd "$1/repodata/repomd.xml"
fi

echo "All packages signed successfully"
```

---

## Key Selection

### Available Keys

```bash
# List configured keys
curl -k https://gamera:5050/api/v1/keys
```

**Response:**
```json
{
  "keys": [
    {
      "type": "legacy",
      "key_id": "4520AFA9",
      "fingerprint": "...",
      "description": "Legacy signing key for EL7/EL8"
    },
    {
      "type": "modern",
      "key_id": "CB2C73F04F3BE076",
      "fingerprint": "...",
      "description": "Modern signing key for EL9+",
      "is_default": true
    }
  ]
}
```

### Choosing the Right Key

- **`modern`** - Use for EL9+, Fedora 38+
- **`legacy`** - Use for EL7, EL8, older systems

```bash
# Modern key (default)
chelon-sign-rpm package.rpm

# Legacy key (explicit)
chelon-sign-rpm --key-type legacy package.rpm
```

---

## Verifying Signatures

### Verify RPM Signature

```bash
# Check signature
rpm -K package.rpm

# Expected output:
# package.rpm: digests signatures OK
```

### Verify Repository Metadata

```bash
# Verify repomd.xml signature
gpg --verify repomd.xml.asc repomd.xml

# Expected output:
# gpg: Signature made ...
# gpg: Good signature from "Atomicorp Signing Key"
```

---

## Troubleshooting

### Authentication Failed

```
HTTP 401: Invalid token
```

**Solution:**
```bash
# Check token format (should be token_id:secret)
echo $CHELON_TOKEN

# Verify token exists on server
sudo chelon-admin list-tokens
```

### Certificate Errors

```
SSL certificate problem: self signed certificate
```

**Solution:**
```bash
# For testing, use -k flag
curl -k https://...

# For production, ensure CA cert is correct
ls -la ~/.chelon/certs/chelon_ca.crt
```

### Rate Limit Exceeded

```
HTTP 429: Rate limit exceeded
```

**Solution:**
Wait for rate limit window to reset (1 hour), or contact admin to increase limit.

### Connection Refused

```
Failed to connect to gamera.atomicorp.com port 5050
```

**Solution:**
```bash
# Check if service is running
sudo systemctl status chelon

# Check firewall
sudo firewall-cmd --list-all | grep 5050
```

---

## Best Practices

1. **Use Environment Variables** - Don't hardcode tokens in scripts
2. **Verify Signatures** - Always verify after signing
3. **Handle Errors** - Check exit codes in scripts
4. **Use Correct Key** - Modern for new systems, legacy for old
5. **Monitor Rate Limits** - Track usage to avoid hitting limits

---

## Advanced Usage

### Batch Signing

```bash
#!/bin/bash
# Sign all RPMs in parallel (careful with rate limits)

find dist/ -name "*.rpm" | \
  xargs -P 4 -I {} chelon-sign-rpm {}
```

### Conditional Signing

```bash
# Only sign if not already signed
if ! rpm -K package.rpm | grep -q "pgp"; then
    chelon-sign-rpm package.rpm
fi
```

### Custom Certificate Paths

```python
client = ChelonClient(
    url="https://gamera.atomicorp.com:5050",
    token=os.environ['CHELON_TOKEN'],
    cert_dir="/custom/path/to/certs",
    verify_ssl=True
)
```

---

## API Reference

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/health` | GET | Health check |
| `/api/v1/keys` | GET | List available keys |
| `/api/v1/sign/rpm` | POST | Sign RPM package |
| `/api/v1/sign/repodata` | POST | Sign repository metadata |

### Request Format

```json
{
  "data": "base64_encoded_data",
  "key_type": "modern"
}
```

### Response Format

```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----...",
  "key_id": "CB2C73F04F3BE076",
  "key_fingerprint": "1234567890ABCDEF...",
  "request_id": "unique-request-id",
  "timestamp": "2026-01-07T15:30:00Z"
}
```

### Error Responses

```json
{
  "error": "Invalid token",
  "request_id": "unique-request-id"
}
```

**Common Error Codes:**
- `400` - Bad request (invalid data)
- `401` - Authentication failed
- `429` - Rate limit exceeded
- `500` - Server error
