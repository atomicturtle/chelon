"""
Signing Engine for Chelon
Handles GPG signing operations using python-gnupg
"""

import gnupg
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class SigningEngine:
    """GPG signing engine"""
    
    # Key mapping
    KEYS = {
        'legacy': '4520AFA9',
        'modern': 'CB2C73F04F3BE076'
    }
    
    def __init__(self, gnupg_home=None):
        """Initialize GPG instance"""
        self.gpg = gnupg.GPG(gnupghome=gnupg_home)
        logger.info("Signing engine initialized")
    
    def get_key_id(self, key_type: str) -> str:
        """Get key ID for a given key type"""
        if key_type not in self.KEYS:
            raise ValueError(f"Unknown key type: {key_type}")
        return self.KEYS[key_type]
    
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
        for key_type, key_id in self.KEYS.items():
            # Check if key exists in keyring
            key_list = self.gpg.list_keys(keys=[key_id])
            if key_list:
                key_info = key_list[0]
                keys.append({
                    'type': key_type,
                    'key_id': key_id,
                    'fingerprint': key_info.get('fingerprint'),
                    'uids': key_info.get('uids', [])
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
