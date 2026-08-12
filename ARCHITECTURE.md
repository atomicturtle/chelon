# Blind Oracle / Chelon: Remote Package Signing Service

## Overview
Chelon (historically "Blind Oracle") is a secure, remote signing service that holds OpenPGP private keys and signs RPM packages and repository metadata on behalf of build servers. Build servers never have access to private keys, significantly reducing the attack surface.

Clients send signing **payloads** (full files for detached signatures, or digest streams from `rpmsign` for integrated signing) over HTTPS and receive ASCII-armored OpenPGP signatures. Classical keys use GnuPG; V6 dual-sign keys use Sequoia (`sq`). Key names are opaque aliases; `backend` in `keys.json` selects the implementation. RPM **dual-sign** is packaging policy (prefer EL9 before EL10).

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Build Server (GitLab Runner)            │
│                                                              │
│  ┌──────────────┐      ┌─────────────────────────────────┐ │
│  │ gitlab-build │─────▶│ chelon-sign                     │ │
│  │     *.sh     │      │  (--resign / --dual-sign)       │ │
│  └──────────────┘      └─────────────────────────────────┘ │
│                                 │                            │
│                                 │ HTTPS POST                 │
│                                 │ {data: base64, key_type}   │
└─────────────────────────────────┼────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Chelon Server                             │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  HTTP API (Flask)                                   │   │
│  │  - POST /api/v1/sign/rpm                            │   │
│  │  - POST /api/v1/sign/repodata                       │   │
│  │  - GET /api/v1/health                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Signing Engine                                     │   │
│  │  - Key selection (named aliases)                    │   │
│  │  - GnuPG or Sequoia by backend                      │   │
│  │  - Audit logging                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Key stores                                         │   │
│  │  - GnuPG: classical aliases (legacy / modern)       │   │
│  │  - Sequoia: V6 aliases (often named pqc)            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Security Model

### Threat Mitigation
1. **Build Server Compromise**: Private keys never leave Chelon
2. **Network Interception**: HTTPS + API token authentication
3. **Unauthorized Signing**: Token-based access control + audit logs
4. **Key Compromise**: Master key offline, only signing subkeys on Chelon

### Authentication
- API tokens per build server
- Token rotation capability
- Rate limiting per token

### Audit Trail
- All signing requests logged with:
  - Timestamp
  - Requesting server (token ID)
  - Payload hash (SHA-256 of signed bytes)
  - Key used
  - Success/failure

## API Specification

### POST /api/v1/sign/rpm
Sign RPM-related payload bytes (full RPM for detached, or digest stream from `rpmsign`).

**Request:**
```json
{
  "data": "<base64-encoded-bytes>",
  "key_type": "modern"
}
```

**Response:**
```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----...",
  "key_id": "CB2C73F04F3BE076",
  "key_fingerprint": "...",
  "request_id": "...",
  "timestamp": "2026-01-06T11:25:00Z"
}
```

Use `key_type: "<alias>"` (e.g. `modern` or `pqc`) for digests during dual-sign. Permission remains `sign:rpm`. Sequoia vs GnuPG is selected via `backend` in `keys.json`, not a PQC API field.

### POST /api/v1/sign/repodata
Sign repository metadata (repomd.xml). **Classical GPG keys only** — Sequoia backends are rejected.

**Request:**
```json
{
  "data": "<base64-encoded-repomd.xml>",
  "key_type": "modern"
}
```

**Response:**
```json
{
  "signature": "-----BEGIN PGP SIGNATURE-----...",
  "key_id": "CB2C73F04F3BE076",
  "request_id": "...",
  "timestamp": "2026-01-06T11:25:00Z"
}
```

## Deployment Notes

- Server: Fedora 43+ or EL10.1+ when enabling Sequoia (`Requires: sequoia-sq`).
- Client: `Requires: sequoia-sq`, `gnupg2`, and `rpm-sign` so builders get ``sq`` for dearmor/RPMv6 without manual setup.
- Dual-sign clients: `rpm-sign` with `--rpmv6` to produce V6 signatures.
- Roll out dual-signed RPMs on **EL9 first**; EL10 only after V6 pubkey trust (see `docs/SIGNING_STRATEGY.md`).

## File Structure
```
chelon/
├── ARCHITECTURE.md
├── README.md
├── docs/
│   ├── SIGNING_STRATEGY.md
│   └── USAGE.md
├── server/
│   ├── chelon-service.py
│   ├── signing_engine.py
│   ├── auth.py
│   └── audit.py
├── tools/
│   ├── chelon-sign
│   ├── chelon-admin
│   └── chelon_client.py
├── config/
│   └── chelon.conf
├── systemd/
│   └── chelon.service
└── tests/
```
