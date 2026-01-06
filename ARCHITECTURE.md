# Blind Oracle: Remote Package Signing Service

## Overview
The Blind Oracle is a secure, remote signing service that holds GPG private keys and signs RPM packages and repository metadata on behalf of build servers. Build servers never have access to private keys, significantly reducing the attack surface.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Build Server (GitLab Runner)            │
│                                                              │
│  ┌──────────────┐      ┌─────────────────────────────────┐ │
│  │ gitlab-build │─────▶│ sign-package.sh                 │ │
│  │    -4.sh     │      │  (Client Mode)                  │ │
│  └──────────────┘      └─────────────────────────────────┘ │
│                                 │                            │
│                                 │ HTTPS POST                 │
│                                 │ {hash, dist, key_type}     │
└─────────────────────────────────┼────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Blind Oracle Server                       │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  HTTP API (Flask/FastAPI)                           │   │
│  │  - POST /sign/rpm                                   │   │
│  │  - POST /sign/repodata                              │   │
│  │  - GET /health                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Signing Engine                                     │   │
│  │  - Key selection (Legacy/Modern)                    │   │
│  │  - GPG signing operations                           │   │
│  │  - Audit logging                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  GPG Keyring (Offline Storage)                      │   │
│  │  - Legacy Key (4520AFA9)                            │   │
│  │  - Modern Key (CB2C73F04F3BE076)                    │   │
│  │  - Passphrases in secure vault                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Security Model

### Threat Mitigation
1. **Build Server Compromise**: Private keys never leave the Oracle
2. **Network Interception**: HTTPS + API token authentication
3. **Unauthorized Signing**: Token-based access control + audit logs
4. **Key Compromise**: Master key offline, only signing subkeys on Oracle

### Authentication
- API tokens per build server
- Token rotation capability
- Rate limiting per token

### Audit Trail
- All signing requests logged with:
  - Timestamp
  - Requesting server (token ID)
  - Package hash
  - Key used
  - Success/failure

## API Specification

### POST /sign/rpm
Sign an RPM package.

**Request:**
```json
{
  "package_hash": "sha256:abc123...",
  "distribution": "el10-x86_64",
  "key_type": "modern",
  "token": "secret-api-token"
}
```

**Response:**
```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----...",
  "key_id": "CB2C73F04F3BE076",
  "timestamp": "2026-01-06T11:25:00Z"
}
```

### POST /sign/repodata
Sign repository metadata (repomd.xml).

**Request:**
```json
{
  "repodata_hash": "sha256:def456...",
  "key_type": "modern",
  "token": "secret-api-token"
}
```

**Response:**
```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----...",
  "key_id": "CB2C73F04F3BE076",
  "timestamp": "2026-01-06T11:25:00Z"
}
```

## Implementation Phases

### Phase 1: Local Prototype (Current)
- ✅ `sign-package.sh` uses local GPG keys
- ✅ Dual key selection logic
- ✅ Deployed to GitLab runners

### Phase 2: Oracle Server (Next)
- [ ] Create Flask/FastAPI service
- [ ] Implement signing endpoints
- [ ] Add authentication/authorization
- [ ] Deploy to secure server
- [ ] Audit logging

### Phase 3: Client Integration
- [ ] Update `sign-package.sh` to detect Oracle mode
- [ ] Implement HTTP client for signing requests
- [ ] Fallback to local signing if Oracle unavailable
- [ ] Token management

### Phase 4: Production Hardening
- [ ] HTTPS with mutual TLS
- [ ] Hardware Security Module (HSM) integration
- [ ] High availability / redundancy
- [ ] Monitoring and alerting
- [ ] Key rotation automation

## Deployment Model

### Development/Testing
- Oracle runs on `winona7` (local development)
- Build servers use API token for testing

### Production
- Oracle runs on dedicated, hardened server
- Firewall rules: Only GitLab runners can access
- Private keys stored in encrypted volume
- Regular backups of audit logs

## File Structure
```
blind-oracle/
├── ARCHITECTURE.md          # This file
├── SIGNING_STRATEGY.md      # GPG key strategy (existing)
├── server/
│   ├── oracle-service.py    # Main Flask/FastAPI app
│   ├── signing_engine.py    # GPG signing logic
│   ├── auth.py              # Token authentication
│   ├── audit.py             # Audit logging
│   └── requirements.txt     # Python dependencies
├── client/
│   ├── sign-package.sh      # Updated with Oracle support
│   └── oracle-client.py     # Python client library
├── deployment/
│   ├── systemd/
│   │   └── oracle.service   # Systemd unit file
│   ├── nginx/
│   │   └── oracle.conf      # Nginx reverse proxy config
│   └── docker/
│       └── Dockerfile       # Container image
└── tests/
    ├── test_signing.py      # Unit tests
    └── test_integration.py  # Integration tests
```

## Next Steps
1. Implement basic Flask service with `/sign/rpm` endpoint
2. Create Python signing engine using `gpg` library
3. Update `sign-package.sh` to support Oracle mode
4. Test end-to-end signing workflow
5. Add authentication and audit logging
