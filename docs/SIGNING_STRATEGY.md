# Atomicorp GPG Signing Strategy & Chelon Process

## Overview
This document outlines the cryptographic strategy for signing Atomicorp software artifacts.
Due to conflicting requirements between legacy systems (requiring SHA-1) and modern systems (requiring SHA-256+), a **Dual Key Strategy** is enforced.

## 1. Key Architecture (Classical + RPMv6)

Keys in Chelon are **named aliases** with a `backend` (`gpg` or `sequoia`). “PQC” is a crypto property of the Sequoia key material (today: ML-DSA-87+Ed448), not a Chelon key type. The usual V6 alias is `pqc` by convention only—any name with `backend: sequoia` works.

**RPM dual-sign** (classical V4 + V6 on the same package) is durable packaging policy until the verifier matrix no longer needs V4—not a temporary PQC branding feature.

| Feature | **Legacy Key** | **Modern Key (2026+)** | **V6 key (convention: `pqc`)** |
| :--- | :--- | :--- | :--- |
| **Purpose** | Support EL5–EL8 | Support EL9+, Fedora, AL2023 | RPMv6 signatures (PQ algorithms today) |
| **Backend** | GnuPG (`gpg`) | GnuPG (`gpg`) | Sequoia (`sequoia`) |
| **Algorithm** | RSA with SHA-1 | RSA 4096 with SHA-256 | Hybrid **ML-DSA-87+Ed448** (rfc9580) |
| **Key ID** | `4520AFA9` | *(per rotation)* | Sequoia fingerprint |
| **Filename** | `RPM-GPG-KEY.atomicorp.txt` | `RPM-GPG-KEY.atomicorp.YYYY.txt` | V6/PQC pubkey package / `.asc` |
| **Chelon name** | `legacy` | `modern` | any alias (often `pqc`) |

### Usage Rules
*   **Legacy Builds**: Must continue using `4520AFA9` to avoid breaking `rpm` on systems with older crypto libraries.
*   **Modern Builds**: Must use the `YYYY` key to comply with FIPS and `DEFAULT` crypto policies that reject SHA-1.
*   **Dual-sign**: Classical RPMv4 resign first, then `rpmsign --addsign --rpmv6` with a Sequoia-backed key. Never `--resign` for the V6 step.
*   **Repodata**: Classical detached GPG only. Sequoia-backed keys must not sign `repomd.xml`.
*   **Rollout order (important)**:
    *   **EL9 first** — stock `rpm` ignores V6; classical V4 still verifies. Safe beachhead for dual-signed RPMs.
    *   **EL9 + multisig/pqrpm** — may enforce V6; treat like EL10 (pubkey first).
    *   **EL10 / Rocky 10.1+ last** — any V6 present means V4 is ignored. Ship the V6 **public** key to clients **before** enabling dual-sign for EL10 packages. See rpm-lab `RESULTS.md`.
*   Callers should use separate gates (e.g. `DUAL_SIGN_EL9=1` vs `DUAL_SIGN_EL10=0`), not a single “enable PQC” switch.

---

## 2. Key Lifecycle Strategy

To minimize risk and support long-term stability, we employ a **Master Key + Subkeys** architecture with a 10-year rotation cycle.

### Structure
1.  **Master Key (Offline)**
    *   **Role**: Identity Root. Used *only* to Certify (issue/revoke) subkeys.
    *   **Storage**: Offline / Air-gapped.
    *   **Expiration**: None (or very long).
2.  **Signing Subkey (Online)**
    *   **Role**: artifact Signing. Lives on the build server / Chelon.
    *   **Expiration**: **10 Years**.
    *   **Rotation**: Every 2 years (soft rotation) or upon expiration/compromise.

### Recovery Plan
If the build server is compromised:
1.  Retrieve the Offline Master Key.
2.  **Revoke** the specific Signing Subkey involved.
3.  **Issue** a new Signing Subkey.
4.  Publish the updated Public Key (containing the revocation and new subkey).
5.  *Identity Continuity*: The "Atomicorp" identity (Master Key) remains trusted; only the compromised "hand" (subkey) is burned.

---

## 3. Key Generation Process

**WARNING**: Perform these steps on a trusted, secure, offline machine. Never on the build server.

### 3.1 Generate Master Key
```bash
gpg --quick-generate-key "Atomicorp (Modern Signing Key) <support@atomicorp.com>" rsa4096 cert never
```

### 3.2 Add Signing Subkey (10-Year Validity)
Get the **Fingerprint** of the new master key (Required for `quick-add-key`):
```bash
# Get the full fingerprint (Field 10)
FPR=$(gpg --list-keys --with-colons "support@atomicorp.com" | awk -F: '/^fpr/ {print $10; exit}')
```

Create the signing subkey:
```bash
gpg --quick-add-key $FPR rsa4096 sign 10y
```

### 3.3 Create Revocation Certificate
**CRITICAL**: Store this file in a secure, offline location (e.g., printed QR code, safe).
```bash
gpg --gen-revoke $FPR > atomicorp_revocation.asc
```

### 3.4 Export Keys

First, identify the **Signing Subkey ID**. This is what goes into the build configuration.
```bash
# Get the ID of the subkey (sub) that has signing capability
SUBKEY_ID=$(gpg --list-keys --with-colons "support@atomicorp.com" | grep "^sub" | tail -n1 | cut -d: -f5)
echo "Signing Key ID: $SUBKEY_ID"
```

**Public Key** (For distribution to users/repos - exports the whole identity):
```bash
gpg --armor --export $FPR > RPM-GPG-KEY.atomicorp.2026.txt
```

**Private Signing Subkey** (For the Build Server / Chelon):
*Note: This exports the subkeys but NOT the master key secret.*
```bash
gpg --export-secret-subkeys --armor $FPR > signing_keys_2026.asc
```

---

## 4. Implementation Details

### Build System Integration
The build system uses wrappers that call Chelon rather than holding private keys locally.

*   **Classical**: Build runners POST the RPM digest / payload to Chelon (`POST /api/v1/sign/rpm`); `chelon-sign --resign` embeds the returned signature via `rpmsign` with Chelon as `__gpg`.
*   **Dual-sign (RPM policy)**: `chelon-sign --dual-sign --key-name modern --v6-key pqc pkg.rpm` — classical resign, then Sequoia-backed `--addsign --rpmv6`. Prefer enabling for **EL9 first**; keep EL10 classical-only until V6 pubkeys are deployed.
*   **Key selection**:
    *   `el5`–`el8`: **Legacy** classical key (usually no dual-sign required).
    *   `el9`: **Modern** classical key; dual-sign when `DUAL_SIGN_EL9` (or equivalent) is on.
    *   `el10`: **Modern** classical key; dual-sign only after V6 pubkey trust (`DUAL_SIGN_EL10`).
*   **Server host**: Sequoia-backed keys require Chelon on Fedora 43+ or EL10.1+ with `sequoia-sq`. Classical keys remain in GnuPG (`GNUPGHOME`); Sequoia secrets under `CHELON_SEQUOIA_HOME` (default `/var/lib/chelon/.sequoia`).
*   **Dual-sign client host**: Must have `rpm-sign` with `--rpmv6` (RPM 6) to *produce* dual-signed packages (build runner), independent of which distro the RPM targets.
*   **API**: always `key_type: "<alias>"` — no PQC-specific API field. Routing uses `backend` in `keys.json`.
*   **Client guardrails**: `chelon-sign` queries `GET /api/v1/keys` and refuses `--resign` with a sequoia-backed key or `--addsign-v6` with a gpg-backed key (skip with `CHELON_SKIP_BACKEND_CHECK=1`).
