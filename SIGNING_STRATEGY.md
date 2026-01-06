# Atomicorp GPG Signing Strategy & Chelon Process

## Overview
This document outlines the cryptographic strategy for signing Atomicorp software artifacts.
Due to conflicting requirements between legacy systems (requiring SHA-1) and modern systems (requiring SHA-256+), a **Dual Key Strategy** is enforced.

## 1. Dual Key Architecture

We maintain two distinct signing identities to support the full range of supported operating systems.

| Feature | **Legacy Key** | **Modern Key (2026+)** |
| :--- | :--- | :--- |
| **Purpose** | Support EL5, EL6, EL7, EL8 | Support EL9, EL10, Fedora, Amazon Linux 2023 |
| **Algorithm** | RSA with SHA-1 (Digest Algo 2) | RSA 4096 with SHA-256 (Digest Algo 8) |
| **Key ID** | `4520AFA9` | *(Generated per rotation cycle)* |
| **Filename** | `RPM-GPG-KEY.atomicorp.txt` | `RPM-GPG-KEY.atomicorp.YYYY.txt` (e.g., `.2026.txt`) |

### Usage Rules
*   **Legacy Builds**: Must continue using `4520AFA9` to avoid breaking `rpm` on systems with older crypto libraries.
*   **Modern Builds**: Must use the `YYYY` key to comply with FIPS and `DEFAULT` crypto policies that reject SHA-1.

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
The build system uses a wrapper script (`sign-package.sh`) to abstract key selection.

*   **Logic**:
    *   Input: `Distribution Name` (e.g., `el7`, `el10`).
    *   Decision:
        *   `el5` - `el8`: Select **Legacy Key**.
        *   `el9`+: Select **Modern Key**.
    *   Instead of local GPG signing, the wrapper will eventually send the file hash to a remote "Chelon" service.
    *   The Chelon service holds the `signing_keys_YYYY.asc` and returns the signature.
    *   This prevents private keys from existing on the build runners themselves.
