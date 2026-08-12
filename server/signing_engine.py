"""
Signing Engine for Chelon

Handles detach-signing via GnuPG (classical) or Sequoia (RPMv6 / ML-DSA keys).
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import gnupg

logger = logging.getLogger(__name__)

BACKEND_GPG = "gpg"
BACKEND_SEQUOIA = "sequoia"
VALID_BACKENDS = {BACKEND_GPG, BACKEND_SEQUOIA}


class SigningEngine:
    """Multi-backend signing engine (GnuPG + Sequoia)."""

    def __init__(
        self,
        gnupg_home: Optional[str] = None,
        keys_file: Optional[str] = None,
        sequoia_home: Optional[str] = None,
        sq_binary: str = "sq",
    ):
        """Initialize backends and load key configuration.

        Args:
            gnupg_home: Path to GPG home directory (defaults to GNUPGHOME / user default).
            keys_file: Path to keys.json configuration file (required).
            sequoia_home: Path to Sequoia home (defaults to CHELON_SEQUOIA_HOME / SEQUOIA_HOME).
            sq_binary: Path to the ``sq`` executable.
        """
        if not keys_file:
            raise ValueError("keys_file is required. Please provide path to keys.json configuration.")

        self.gpg = gnupg.GPG(gnupghome=gnupg_home)
        self.gnupg_home = gnupg_home
        self.sequoia_home = (
            sequoia_home
            or os.environ.get("CHELON_SEQUOIA_HOME")
            or os.environ.get("SEQUOIA_HOME")
        )
        self.sq_binary = sq_binary
        self.keys_file = Path(keys_file)
        self.keys = {}
        self.default_key = None

        self._load_keys()
        logger.info("Signing engine initialized with %d keys", len(self.keys))

    def _load_keys(self) -> None:
        """Load keys from configuration file.

        Raises:
            FileNotFoundError: If keys file doesn't exist.
            ValueError: If keys file is invalid or empty.
        """
        if not self.keys_file.exists():
            raise FileNotFoundError(
                f"Keys configuration file not found: {self.keys_file}\n"
                f"Please create it using: chelon-admin keys add <name> <key_id>"
            )

        try:
            with open(self.keys_file, "r") as f:
                config = json.load(f)

            self.keys = config.get("keys", {})
            self.default_key = config.get("default_key")

            if not self.keys:
                raise ValueError(
                    f"No keys configured in {self.keys_file}\n"
                    f"Please add keys using: chelon-admin keys add <name> <key_id>"
                )

            for key_name, key_info in self.keys.items():
                if not key_info.get("enabled", True):
                    continue
                backend = self._normalize_backend(key_info.get("backend"))
                key_info["backend"] = backend
                key_id = key_info["key_id"]
                if backend == BACKEND_GPG:
                    if not self.gpg.list_keys(keys=[key_id]):
                        logger.warning(
                            "Key '%s' (%s) not found in GPG keyring", key_name, key_id
                        )
                elif backend == BACKEND_SEQUOIA:
                    if not self._sequoia_key_present(key_id):
                        logger.warning(
                            "Key '%s' (%s) not found in Sequoia home %s",
                            key_name,
                            key_id,
                            self.sequoia_home or "(default)",
                        )

            logger.info("Loaded %d keys from %s", len(self.keys), self.keys_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in keys file {self.keys_file}: {e}") from e
        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            raise ValueError(f"Failed to load keys from {self.keys_file}: {e}") from e

    @staticmethod
    def _normalize_backend(backend: Optional[str]) -> str:
        """Return a validated backend name; missing/empty means gpg."""
        if not backend:
            return BACKEND_GPG
        backend = backend.lower().strip()
        if backend not in VALID_BACKENDS:
            raise ValueError(
                f"Unknown backend '{backend}'. Valid backends: {', '.join(sorted(VALID_BACKENDS))}"
            )
        return backend

    def _sq_base_cmd(self) -> List[str]:
        """Build the base ``sq`` command with optional --home."""
        cmd = [self.sq_binary]
        if self.sequoia_home:
            cmd.extend(["--home", self.sequoia_home])
        return cmd

    def _sequoia_key_present(self, key_id: str) -> bool:
        """Return True if fingerprint/key ID exists in the Sequoia key store."""
        try:
            result = subprocess.run(
                self._sq_base_cmd() + ["key", "list", "--cert", key_id],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            return result.returncode == 0
        except FileNotFoundError:
            logger.warning("'%s' not found; cannot validate Sequoia keys", self.sq_binary)
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Timed out listing Sequoia key %s", key_id)
            return False

    def reload_keys(self) -> None:
        """Reload keys from configuration file."""
        logger.info("Reloading key configuration")
        self._load_keys()

    def get_key_info(self, key_type: str) -> Dict:
        """Return the configured key record for a name or key ID.

        Raises:
            ValueError: If key type/ID is unknown or disabled.
        """
        if key_type in self.keys:
            key_info = self.keys[key_type]
            if not key_info.get("enabled", True):
                raise ValueError(f"Key type '{key_type}' is disabled")
            return key_info

        for info in self.keys.values():
            if info["key_id"].upper() == key_type.upper():
                if not info.get("enabled", True):
                    raise ValueError(f"Key ID '{key_type}' is disabled")
                return info

        raise ValueError(f"Unknown key type or ID: {key_type}")

    def get_backend(self, key_type: str) -> str:
        """Return backend name for a key type or ID."""
        return self._normalize_backend(self.get_key_info(key_type).get("backend"))

    def is_sequoia_key(self, key_type: str) -> bool:
        """Return True if the key uses the Sequoia backend."""
        return self.get_backend(key_type) == BACKEND_SEQUOIA

    def get_key_id(self, key_type: str) -> str:
        """Get key ID / fingerprint for a given key type or ID."""
        return self.get_key_info(key_type)["key_id"]

    def get_key_name(self, key_type: str) -> str:
        """Get the configured name of a key from an alias or ID."""
        if key_type in self.keys:
            return key_type

        for name, info in self.keys.items():
            if info["key_id"].upper() == key_type.upper():
                return name

        raise ValueError(f"Unknown key type or ID: {key_type}")

    def get_key_fingerprint(self, key_type: str) -> Optional[str]:
        """Get full fingerprint for a given key type."""
        key_id = self.get_key_id(key_type)
        backend = self.get_backend(key_type)
        if backend == BACKEND_SEQUOIA:
            return key_id
        key_list = self.gpg.list_keys(keys=[key_id])
        if key_list:
            return key_list[0].get("fingerprint")
        return None

    def list_keys(self) -> List[Dict]:
        """List available signing keys that are present in their backend store."""
        keys = []
        for key_type, key_info in self.keys.items():
            key_id = key_info["key_id"]
            backend = self._normalize_backend(key_info.get("backend"))
            entry = {
                "type": key_type,
                "key_id": key_id,
                "backend": backend,
                "description": key_info.get("description", ""),
                "enabled": key_info.get("enabled", True),
                "is_default": key_type == self.default_key,
            }
            if backend == BACKEND_GPG:
                key_list = self.gpg.list_keys(keys=[key_id])
                if not key_list:
                    continue
                gpg_key_info = key_list[0]
                entry["fingerprint"] = gpg_key_info.get("fingerprint")
                entry["uids"] = gpg_key_info.get("uids", [])
            else:
                if not self._sequoia_key_present(key_id):
                    continue
                entry["fingerprint"] = key_id
                entry["uids"] = []
            keys.append(entry)
        return keys

    def list_configured_keys(self) -> List[Dict]:
        """List all configured keys (including those not in a key store)."""
        keys = []
        for key_type, key_info in self.keys.items():
            key_id = key_info["key_id"]
            backend = self._normalize_backend(key_info.get("backend"))
            if backend == BACKEND_GPG:
                in_keyring = bool(self.gpg.list_keys(keys=[key_id]))
            else:
                in_keyring = self._sequoia_key_present(key_id)

            keys.append(
                {
                    "name": key_type,
                    "key_id": key_id,
                    "backend": backend,
                    "description": key_info.get("description", ""),
                    "enabled": key_info.get("enabled", True),
                    "in_keyring": in_keyring,
                    "is_default": key_type == self.default_key,
                }
            )
        return keys

    def sign_data(self, data: bytes, key_type: str, passphrase: str = None) -> str:
        """Sign data using the backend configured for the key.

        Args:
            data: Data to sign.
            key_type: Name or ID of the key to use.
            passphrase: Optional passphrase (GnuPG only today).

        Returns:
            ASCII-armored OpenPGP detached signature.
        """
        key_id = self.get_key_id(key_type)
        backend = self.get_backend(key_type)
        logger.info("Signing data with %s key (%s) via %s", key_type, key_id, backend)

        if backend == BACKEND_SEQUOIA:
            return self._sign_sequoia(data, key_id)
        return self._sign_gpg(data, key_id, passphrase)

    def _sign_gpg(self, data: bytes, key_id: str, passphrase: Optional[str]) -> str:
        """Detach-sign with python-gnupg."""
        signed = self.gpg.sign(
            data,
            keyid=key_id,
            passphrase=passphrase,
            detach=True,
            clearsign=False,
            extra_args=["--pinentry-mode", "loopback"],
        )

        if not signed:
            raise Exception(f"Signing failed: {signed.stderr}")

        signature = str(signed)
        logger.info("Successfully signed with GPG key %s", key_id)
        return signature

    def _sign_sequoia(self, data: bytes, key_id: str) -> str:
        """Detach-sign with ``sq`` and return an armored signature string."""
        if not self._sequoia_key_present(key_id):
            raise Exception(
                f"Sequoia key '{key_id}' not found in home "
                f"{self.sequoia_home or '(default)'}"
            )

        with tempfile.TemporaryDirectory(prefix="chelon-sq-") as tmp:
            data_path = os.path.join(tmp, "payload.bin")
            sig_path = os.path.join(tmp, "payload.sig")
            with open(data_path, "wb") as f:
                f.write(data)

            cmd = self._sq_base_cmd() + [
                "sign",
                "--signer",
                key_id,
                "--signature-file",
                sig_path,
                "--",
                data_path,
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
            except FileNotFoundError as e:
                raise Exception(
                    f"Sequoia 'sq' binary not found ({self.sq_binary}). "
                    "Install sequoia-sq on the Chelon host."
                ) from e
            except subprocess.TimeoutExpired as e:
                raise Exception(f"Sequoia signing timed out for key {key_id}") from e

            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                raise Exception(f"Sequoia signing failed: {err}")

            with open(sig_path, "r", encoding="utf-8") as f:
                signature = f.read()

            if not signature.strip():
                raise Exception("Sequoia signing produced an empty signature")

        logger.info("Successfully signed with Sequoia key %s", key_id)
        return signature

    def verify_signature(self, data: str, signature: str) -> bool:
        """Verify a GPG signature (classical GnuPG path only)."""
        verified = self.gpg.verify_data(signature.encode(), data.encode())
        return verified.valid
