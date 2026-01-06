# Blind Oracle Implementation Plan

## Goal
Implement a secure, remote GPG signing service (Blind Oracle) that eliminates the need for private keys on build servers. Build servers will send package hashes to the Oracle via HTTPS API, and receive signatures in response.

## Phase 1: Core Signing Service

### Server Components

#### 1. Flask API Service (`server/oracle-service.py`)
**Purpose**: HTTP API for signing requests

**Endpoints**:
- `POST /api/v1/sign/rpm` - Sign RPM package
- `POST /api/v1/sign/repodata` - Sign repository metadata  
- `GET /api/v1/health` - Health check
- `GET /api/v1/keys` - List available signing keys

**Dependencies**:
- Flask or FastAPI
- python-gnupg
- Request validation (pydantic)

#### 2. Signing Engine (`server/signing_engine.py`)
**Purpose**: GPG signing operations

**Functions**:
- `sign_data(data_hash, key_type)` - Sign arbitrary data
- `verify_signature(data, signature)` - Verify signatures
- `list_keys()` - Get available keys

**Key Selection Logic**:
```python
def select_key(key_type: str) -> str:
    if key_type == "modern":
        return "CB2C73F04F3BE076"
    elif key_type == "legacy":
        return "4520AFA9"
    else:
        raise ValueError(f"Unknown key type: {key_type}")
```

#### 3. Authentication (`server/auth.py`)
**Purpose**: API token validation

**Features**:
- Token-based authentication
- Token storage (file or database)
- Rate limiting per token
- Token rotation capability

**Token Format**:
```json
{
  "token_id": "runner-gamera-001",
  "secret": "randomly-generated-secret",
  "permissions": ["sign:rpm", "sign:repodata"],
  "rate_limit": 100,
  "created": "2026-01-06T00:00:00Z"
}
```

#### 4. Audit Logging (`server/audit.py`)
**Purpose**: Track all signing operations

**Log Format**:
```json
{
  "timestamp": "2026-01-06T11:25:00Z",
  "token_id": "runner-gamera-001",
  "operation": "sign_rpm",
  "key_used": "CB2C73F04F3BE076",
  "data_hash": "sha256:abc123...",
  "success": true,
  "client_ip": "10.66.6.1"
}
```

---

## Phase 2: Client Integration

### Updated `sign-package.sh`

**Mode Detection**:
```bash
# Check if Oracle is configured
if [ -f ~/.oracle-config ]; then
    # Use Oracle mode
    sign_via_oracle "$RPM_FILE" "$KEY_TYPE"
else
    # Use local GPG (current behavior)
    sign_locally "$RPM_FILE" "$KEY_TYPE"
fi
```

**Oracle Client Function**:
```bash
sign_via_oracle() {
    local rpm_file="$1"
    local key_type="$2"
    
    # Calculate hash
    local hash=$(sha256sum "$rpm_file" | cut -d' ' -f1)
    
    # Read Oracle config
    source ~/.oracle-config
    
    # Call Oracle API
    local response=$(curl -X POST \
        -H "Authorization: Bearer $ORACLE_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"package_hash\":\"sha256:$hash\",\"key_type\":\"$key_type\"}" \
        "$ORACLE_URL/api/v1/sign/rpm")
    
    # Extract signature and apply to RPM
    echo "$response" | jq -r '.signature' > /tmp/signature.asc
    rpmsign --addsign --fskpath /tmp/signature.asc "$rpm_file"
}
```

**Configuration File** (`~/.oracle-config`):
```bash
ORACLE_URL="https://oracle.atomicorp.internal:8443"
ORACLE_TOKEN="secret-token-here"
ORACLE_TIMEOUT=30
```

---

## Phase 3: Deployment

### Server Setup

**1. Install Dependencies**:
```bash
pip install flask python-gnupg pydantic
```

**2. Import GPG Keys**:
```bash
# Import both Legacy and Modern keys
gpg --import /path/to/legacy_key.asc
gpg --import /path/to/modern_key.asc
```

**3. Create Systemd Service** (`deployment/systemd/oracle.service`):
```ini
[Unit]
Description=Blind Oracle Signing Service
After=network.target

[Service]
Type=simple
User=oracle
WorkingDirectory=/opt/blind-oracle
ExecStart=/usr/bin/python3 /opt/blind-oracle/server/oracle-service.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**4. Nginx Reverse Proxy** (`deployment/nginx/oracle.conf`):
```nginx
server {
    listen 8443 ssl;
    server_name oracle.atomicorp.internal;
    
    ssl_certificate /etc/ssl/certs/oracle.crt;
    ssl_certificate_key /etc/ssl/private/oracle.key;
    
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Client Setup (GitLab Runners)

**1. Create Oracle Config**:
```bash
cat > ~/.oracle-config << 'EOF'
ORACLE_URL="https://oracle.atomicorp.internal:8443"
ORACLE_TOKEN="runner-gamera-secret-token"
ORACLE_TIMEOUT=30
EOF
chmod 600 ~/.oracle-config
```

**2. Update `sign-package.sh`**:
- Deploy updated version with Oracle support
- Test fallback to local signing

---

## Verification Plan

### Unit Tests
```bash
# Test signing engine
python -m pytest tests/test_signing.py

# Test API endpoints
python -m pytest tests/test_api.py
```

### Integration Tests
1. Start Oracle service locally
2. Configure test client with Oracle URL
3. Sign test RPM via Oracle
4. Verify signature on EL10 system

### Security Tests
- [ ] Test invalid tokens (should reject)
- [ ] Test rate limiting (should throttle)
- [ ] Test network failure (should fallback to local)
- [ ] Verify audit logs are created

---

## Rollout Plan

### Stage 1: Development Testing
- Oracle runs on `winona7:5000`
- Single test runner (`gamera`) configured
- Test with `awp-agent` EL10 builds

### Stage 2: Staging
- Oracle deployed to dedicated VM
- Both runners (`gamera`, `10.66.6.1`) configured
- Monitor audit logs for issues

### Stage 3: Production
- Oracle hardened (firewall, HTTPS, monitoring)
- All projects using `gitlab-build-4.sh` use Oracle
- Legacy `gitlab-build-2.sh` continues local signing

---

## Security Considerations

### Threat Model
| Threat | Mitigation |
|--------|------------|
| Build server compromise | Keys never on build servers |
| Network interception | HTTPS + token auth |
| Unauthorized signing | Token-based ACL |
| Oracle server compromise | Master key offline, only subkeys on Oracle |
| Token theft | Short-lived tokens, rotation |

### Future Enhancements
- [ ] Mutual TLS (client certificates)
- [ ] Hardware Security Module (HSM) integration
- [ ] Multi-factor authentication for token generation
- [ ] Automated key rotation
- [ ] High availability / load balancing

---

## Next Steps
1. Implement basic Flask service with `/sign/rpm` endpoint
2. Create signing engine using `python-gnupg`
3. Add simple token authentication
4. Test end-to-end signing workflow
5. Deploy to `winona7` for testing
6. Update `sign-package.sh` with Oracle support
