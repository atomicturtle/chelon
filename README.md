# Chelon - Remote GPG Signing Service

Chelon is a secure remote signing service for RPM packages and repository metadata. Build servers send package hashes via HTTPS API and receive GPG signatures, eliminating the need for private keys on build infrastructure.

## Features

- **Remote Signing**: Build servers never touch private keys
- **Dual Key Support**: Separate keys for legacy (EL5-8) and modern (EL9+) distributions
- **Token Authentication**: Secure API access with rate limiting
- **Audit Logging**: All signing operations logged for compliance
- **Systemd Integration**: Runs as unprivileged service with journald logging

## Installation

```bash
sudo dnf install chelon-1.0.0-1.fc43.noarch.rpm
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

### 2. Generate API Token

```bash
# Create a token for your build server
sudo chelon-admin generate-token runner-gamera \
  --permissions sign:rpm,sign:repodata \
  --rate-limit 100

# Save the output token securely!
```

### 3. Start Service

```bash
sudo systemctl enable --now chelon
sudo systemctl status chelon
```

### 4. Test the Service

```bash
# Health check
curl http://localhost:5050/api/v1/health

# List available keys
curl http://localhost:5050/api/v1/keys
```

## Configuration

Edit `/etc/chelon/chelon.conf`:

```bash
# Server binding
ORACLE_HOST=127.0.0.1
ORACLE_PORT=5050

# GPG home directory
GNUPGHOME=/var/lib/chelon/.gnupg

# Logging
LOG_LEVEL=INFO
```

Restart after changes:
```bash
sudo systemctl restart chelon
```

## API Usage

### Sign an RPM Package

```bash
curl -X POST http://localhost:5050/api/v1/sign/rpm \
  -H "Authorization: Bearer YOUR-TOKEN-HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "package_hash": "sha256:abc123...",
    "key_type": "modern"
  }'
```

### Sign Repository Metadata

```bash
curl -X POST http://localhost:5050/api/v1/sign/repodata \
  -H "Authorization: Bearer YOUR-TOKEN-HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "repodata_hash": "sha256:def456...",
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

## File Locations

| Path | Purpose |
|------|---------|
| `/etc/chelon/chelon.conf` | Configuration file |
| `/var/lib/chelon/` | Data directory (GPG keys, tokens, audit log) |
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

## Support

For issues and questions:
- Email: support@atomicorp.com
- Web: https://www.atomicorp.com
