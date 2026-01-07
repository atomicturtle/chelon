"""
Signing Engine for Chelon
Handles GPG signing operations using python-gnupg
"""

import os
import json
import gnupg
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SigningEngine:
    """GPG signing engine"""
    
    def __init__(self, gnupg_home: Optional[str] = None, keys_file: Optional[str] = None):
        """Initialize GPG instance and load key configuration
        
        Args:
            gnupg_home: Path to GPG home directory
            keys_file: Path to keys.json configuration file (required)
        """
        self.gpg = gnupg.GPG(gnupghome=gnupg_home)
        
        if not keys_file:
            raise ValueError("keys_file is required. Please provide path to keys.json configuration.")
        
        self.keys_file = Path(keys_file)
        self.keys = {}
        self.default_key = None
        
        # Load keys from configuration
        self._load_keys()
        
        logger.info(f"Signing engine initialized with {len(self.keys)} keys")
    
    def _load_keys(self) -> None:
        """Load keys from configuration file
        
        Raises:
            FileNotFoundError: If keys file doesn't exist
            ValueError: If keys file is invalid or empty
        """
        if not self.keys_file.exists():
            raise FileNotFoundError(
                f"Keys configuration file not found: {self.keys_file}\n"
                f"Please create it using: chelon-admin keys add <name> <key_id>"
            )
        
        try:
            with open(self.keys_file, 'r') as f:
                config = json.load(f)
            
            self.keys = config.get('keys', {})
            self.default_key = config.get('default_key')
            
            if not self.keys:
                raise ValueError(
                    f"No keys configured in {self.keys_file}\n"
                    f"Please add keys using: chelon-admin keys add <name> <key_id>"
                )
            
            # Validate keys exist in GPG keyring
            for key_name, key_info in self.keys.items():
                if key_info.get('enabled', True):
                    key_id = key_info['key_id']
                    key_list = self.gpg.list_keys(keys=[key_id])
                    if not key_list:
                        logger.warning(f"Key '{key_name}' ({key_id}) not found in GPG keyring")
            
            logger.info(f"Loaded {len(self.keys)} keys from {self.keys_file}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in keys file {self.keys_file}: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load keys from {self.keys_file}: {e}")
    
    def reload_keys(self) -> None:
        """Reload keys from configuration file"""
        logger.info("Reloading key configuration")
        self._load_keys()
    
    def get_key_id(self, key_type: str) -> str:
        """Get key ID for a given key type
        
        Args:
            key_type: Name of the key type
            
        Returns:
            GPG key ID
            
        Raises:
            ValueError: If key type is unknown or disabled
        """
        if key_type not in self.keys:
            raise ValueError(f"Unknown key type: {key_type}")
        
        key_info = self.keys[key_type]
        if not key_info.get('enabled', True):
            raise ValueError(f"Key type '{key_type}' is disabled")
        
        return key_info['key_id']
    
    def get_key_fingerprint(self, key_type: str) -> str:
        """Get full fingerprint for a given key type"""
        key_id = self.get_key_id(key_type)
        key_list = self.gpg.list_keys(keys=[key_id])
        if key_list:
            return key_list[0].get('fingerprint')
        return None
    
    def list_keys(self) -> List[Dict]:
        """List available signing keys"""
        keys = []
        for key_type, key_info in self.keys.items():
            key_id = key_info['key_id']
            # Check if key exists in keyring
            key_list = self.gpg.list_keys(keys=[key_id])
            if key_list:
                gpg_key_info = key_list[0]
                keys.append({
                    'type': key_type,
                    'key_id': key_id,
                    'fingerprint': gpg_key_info.get('fingerprint'),
                    'uids': gpg_key_info.get('uids', []),
                    'description': key_info.get('description', ''),
                    'enabled': key_info.get('enabled', True),
                    'is_default': key_type == self.default_key
                })
        return keys
    
    def list_configured_keys(self) -> List[Dict]:
        """List all configured keys (including those not in keyring)
        
        Returns:
            List of configured keys with their status
        """
        keys = []
        for key_type, key_info in self.keys.items():
            key_id = key_info['key_id']
            # Check if key exists in keyring
            key_list = self.gpg.list_keys(keys=[key_id])
            in_keyring = bool(key_list)
            
            keys.append({
                'name': key_type,
                'key_id': key_id,
                'description': key_info.get('description', ''),
                'enabled': key_info.get('enabled', True),
                'in_keyring': in_keyring,
                'is_default': key_type == self.default_key
            })
        return keys
    
    def sign_data(self, data: bytes, key_type: str, passphrase: str = None) -> str:
        """
        Sign data using specified key
        
        Args:
            data: Raw data to sign (bytes)
            key_type: Type of key to use ('legacy' or 'modern')
            passphrase: GPG key passphrase
        
        Returns:
            ASCII-armored GPG signature
        """
        key_id = self.get_key_id(key_type)
        
        logger.info(f"Signing data with {key_type} key ({key_id})")
        
        # Sign the data
        signed = self.gpg.sign(
            data,
            keyid=key_id,
            passphrase=passphrase,
            detach=True,
            clearsign=False,
            extra_args=['--pinentry-mode', 'loopback']
        )
        
        if not signed:
            raise Exception(f"Signing failed: {signed.stderr}")
        
        signature = str(signed)
        logger.info(f"Successfully signed with key {key_id}")
        
        return signature
    
    def verify_signature(self, data: str, signature: str) -> bool:
        """
        Verify a GPG signature
        
        Args:
            data: Original data
            signature: ASCII-armored signature
        
        Returns:
            True if signature is valid
        """
        verified = self.gpg.verify_data(signature.encode(), data.encode())
        return verified.valid
