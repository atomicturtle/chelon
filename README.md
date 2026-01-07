# Chelon - Remote GPG Signing Service

Chelon is a secure remote signing service for RPM packages and repository metadata. Build servers send package hashes via HTTPS API and receive GPG signatures, eliminating the need for private keys on build infrastructure.

## Features

- **Remote Signing**: Build servers never touch private keys
- **Dynamic Key Configuration**: Manage signing keys via admin tool without code changes
- **Token Authentication**: Secure API access with rate limiting
- **Audit Logging**: All signing operations logged for compliance
- **Systemd Integration**: Runs as unprivileged service with journald logging
- **mTLS Support**: Optional mutual TLS for enhanced security

## Documentation

- **[Usage Guide](docs/USAGE.md)** - How to sign RPMs and repository metadata
- **[Signing Strategy](docs/SIGNING_STRATEGY.md)** - Technical details on signing approach
- **[Quick Start](#quick-start)** - Get started in 5 minutes
- **[Administration](#administration)** - Key and token management

## Architecture

```
┌─────────────────┐
│  Build Runner   │
└────────┬────────┘
         │ HTTPS + mTLS
         │ (Port 443/5050)
         ▼
┌─────────────────┐
│ Chelon Service  │
│  - Flask API    │
│  - Auth/Tokens  │
│  - Rate Limiting│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Signing Engine  │
│  - GPG Keyring  │
│  - Key Config   │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Audit Logger   │
│  (journald)     │
└─────────────────┘
```

## Installation

```bash
sudo dnf install chelon
```

## Quick Start

### 1. Import GPG Keys

```bash
# Import signing keys as the chelon user
sudo -u chelon gpg --import /path/to/legacy_key.asc
sudo -u chelon gpg --import /path/to/modern_key.asc

# Verify keys are imported
sudo -u chelon gpg --list-keys
```

### 2. Configure Keys

Chelon uses a JSON configuration file to manage signing keys. You must configure at least one key before the service will start.

```bash
# Add your legacy key
sudo chelon-admin keys add legacy 4520AFA9 \
  --description "Legacy signing key for EL7/EL8"

# Add your modern key  
sudo chelon-admin keys add modern CB2C73F04F3BE076 \
  --description "Modern signing key for EL9+"

# Set the default key
sudo chelon-admin keys set-default modern

# List configured keys
sudo chelon-admin keys list
```

**Output:**
```
Name                 Key ID               Status     Default    Description
------------------------------------------------------------------------------------------
legacy               4520AFA9             enabled               Legacy signing key for EL7/EL8
modern               CB2C73F04F3BE076     enabled    ✓          Modern signing key for EL9+
```

> [!IMPORTANT]
> The service will not start without a configured `keys.json` file.
> Use `chelon-admin keys add` to configure your GPG keys.

### 3. Generate API Token

```bash
# Create a token for your build server
sudo chelon-admin generate-token runner-gamera \
  --permissions sign:rpm,sign:repodata \
  --rate-limit 100

# Save the output token securely!
```

### 4. Start Service

```bash
sudo systemctl enable --now chelon
sudo systemctl status chelon
```

### 5. Test the Service

```bash
# Health check
curl -k https://localhost:5050/api/v1/health

# List available keys
curl -k https://localhost:5050/api/v1/keys
```

## Configuration

Edit `/etc/chelon/chelon.conf`:

```bash
# Server binding
CHELON_HOST=127.0.0.1
CHELON_PORT=5050

# GPG home directory
GNUPGHOME=/var/lib/chelon/.gnupg

# Logging
LOG_LEVEL=INFO

# Transport Security (HTTPS/mTLS)
# Paths to your certificate files:
CHELON_SSL_CERT=/etc/chelon/certs/server.crt
CHELON_SSL_KEY=/etc/chelon/certs/server.key
CHELON_SSL_CA=/etc/chelon/certs/ca.crt

# Enforce Client Certificate Authentication (mTLS)
CHELON_SSL_VERIFY_CLIENT=true
```

> [!IMPORTANT]
> Ensure `/etc/chelon/chelon.conf` is readable ONLY by the `chelon` user (`chmod 600`).
> The service contains sensitive passphrases and will refuse to start if permissions are insecure.


Restart after changes:
```bash
sudo systemctl restart chelon
```

## API Usage

### Sign an RPM Package

```bash
curl -k -X POST https://localhost:5050/api/v1/sign/rpm \
  -H "Authorization: Bearer YOUR-TOKEN-HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "data": "sha256:abc123...",
    "key_type": "modern"
  }'
```

### Sign Repository Metadata

```bash
curl -k -X POST https://localhost:5050/api/v1/sign/repodata \
  -H "Authorization: Bearer YOUR-TOKEN-HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "data": "sha256:def456...",
    "key_type": "legacy"
  }'
```

## Administration

### List Tokens

```bash
sudo chelon-admin list-tokens
```

### View Audit Logs

```bash
# Recent activity
sudo chelon-admin audit --limit 50

# Or view raw audit log
sudo cat /var/lib/chelon/audit.log
```

### Revoke a Token

```bash
sudo chelon-admin revoke-token runner-old
```

### View Service Logs

```bash
# Real-time logs
sudo journalctl -u chelon -f

# Recent logs
sudo journalctl -u chelon -n 100
```

## Security

- Service runs as unprivileged `chelon` user
- Private keys stored in `/var/lib/chelon/.gnupg` (mode 0700)
- Tokens hashed with SHA-256
- Rate limiting prevents abuse
- All operations logged to audit trail

## Transport Security (HTTPS/mTLS)

To enable HTTPS and Mutual TLS (mTLS):
1.  **Generate Certificates**: Creating a CA, Server, and Client certificate.
    ```bash
    # Create directory for certs
    sudo mkdir -p /etc/chelon/certs
    
    # Generate CA
    openssl req -x509 -newkey rsa:2048 -keyout ca.key -out ca.crt -days 365 -nodes -subj "/CN=Chelon CA"
    
    # Server Cert
    openssl req -newkey rsa:2048 -keyout server.key -out server.csr -nodes -subj "/CN=chelon-server"
    openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365
    
    # Client Cert
    openssl req -newkey rsa:2048 -keyout client.key -out client.csr -nodes -subj "/CN=build-runner"
    openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -out client.crt -days 365
    
    # Install
    sudo mv *.crt *.key /etc/chelon/certs/
    sudo chown -R chelon:chelon /etc/chelon/certs
    sudo chmod 600 /etc/chelon/certs/*.key
    ```

2.  **Configure Chelon**: Update `/etc/chelon/chelon.conf` with the paths (see Configuration section).

3.  **Client Usage**:
    ```bash
    curl --cert client.crt --key client.key --cacert ca.crt \
         https://chelon-server:5050/api/v1/health
    ```

## File Locations
| Path | Purpose |
|------|---------|
| `/etc/chelon/chelon.conf` | Configuration file |
| `/var/lib/chelon/keys.json` | Key configuration |
| `/var/lib/chelon/tokens.json` | API tokens |
| `/var/lib/chelon/.gnupg` | GPG keyring |
| `/usr/share/chelon/` | Service code |
| `/usr/bin/chelon-admin` | Administration CLI |


## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status chelon

# View detailed logs
sudo journalctl -u chelon -xe
```

### GPG key not found

```bash
# Verify keys are imported for chelon user
sudo -u chelon gpg --list-keys

# Check GPG home directory
ls -la /var/lib/chelon/.gnupg
```

### Authentication failures

```bash
# Verify token exists
sudo chelon-admin list-tokens

# Check audit log for details
sudo chelon-admin audit --limit 20
```

### Keys not configured

```bash
# Check if keys.json exists
ls -la /var/lib/chelon/keys.json

# Add keys
sudo chelon-admin keys add keyname KEYID --description "Description"
```

## Support

For issues and questions:
- **Documentation:** [docs/](docs/)
- **Email:** support@atomicorp.com
- **Web:** https://www.atomicorp.com
