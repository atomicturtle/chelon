#!/usr/bin/env python3
"""
Chelon Client Library

Shared functionality for Chelon client tools.
Handles authentication, API communication, and configuration.
"""

import os
import sys
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urljoin
import urllib.request
import ssl


class ChelonClientError(Exception):
    """Base exception for Chelon client errors"""
    pass


class ChelonClient:
    """Client for communicating with Chelon signing service"""
    
    def __init__(self, 
                 url: Optional[str] = None,
                 token: Optional[str] = None,
                 cert_dir: Optional[str] = None,
                 verify_ssl: Optional[bool] = None):
        """
        Initialize Chelon client
        
        Args:
            url: Chelon service URL (default: from env CHELON_URL or https://localhost:5050)
            token: Authentication token (default: from env CHELON_TOKEN)
            cert_dir: Directory containing client certificates (default: from env CHELON_CERT_DIR or ~/.chelon/certs)
            verify_ssl: Whether to verify SSL certificates (default: from env CHELON_VERIFY_SSL or True)
        """
        self.url = url or os.environ.get('CHELON_URL', 'https://localhost:5050')
        self.token = token or os.environ.get('CHELON_TOKEN')
        self.cert_dir = Path(cert_dir or os.environ.get('CHELON_CERT_DIR', os.path.expanduser('~/.chelon/certs')))
        
        if verify_ssl is None:
            verify_ssl_env = os.environ.get('CHELON_VERIFY_SSL', 'true').lower()
            self.verify_ssl = verify_ssl_env not in ('false', '0', 'no')
        else:
            self.verify_ssl = verify_ssl
        
        if not self.token:
            raise ChelonClientError("No token provided. Set CHELON_TOKEN environment variable or pass token parameter.")
        
        # Validate certificate files exist
        self.client_cert = self.cert_dir / 'chelon_client.crt'
        self.client_key = self.cert_dir / 'chelon_client.key'
        self.ca_cert = self.cert_dir / 'chelon_ca.crt'
        
        if not self.client_cert.exists():
            # Fallback to older names for backward compatibility if new names don't exist
            alt_cert = self.cert_dir / 'client.crt'
            alt_key = self.cert_dir / 'client.key'
            alt_ca = self.cert_dir / 'ca.crt'
            
            if alt_cert.exists() and alt_key.exists():
                self.client_cert = alt_cert
                self.client_key = alt_key
                if alt_ca.exists():
                    self.ca_cert = alt_ca
            else:
                raise ChelonClientError(f"Client certificate not found: {self.client_cert}")
        
        if not self.client_key.exists():
            raise ChelonClientError(f"Client key not found: {self.client_key}")
        if self.verify_ssl and not self.ca_cert.exists():
            raise ChelonClientError(f"CA certificate not found: {self.ca_cert}")
    
    def _ssl_context(self) -> ssl.SSLContext:
        """Build an SSL context for mTLS requests."""
        if self.verify_ssl:
            ca_cert_path = Path(self.ca_cert) if not isinstance(self.ca_cert, Path) else self.ca_cert
            if not ca_cert_path.is_file():
                raise ChelonClientError(f"CA certificate file not found: {ca_cert_path}")
            ssl_context = ssl.create_default_context(cafile=str(ca_cert_path))
        else:
            ssl_context = ssl.create_default_context()

        ssl_context.load_cert_chain(certfile=str(self.client_cert), keyfile=str(self.client_key))

        if not self.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _http_request(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        method: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP request to Chelon.

        Args:
            endpoint: API endpoint (e.g., '/api/v1/sign/rpm' or '/api/v1/keys')
            data: Optional JSON body (implies POST when method not set)
            method: HTTP method (default POST if data else GET)
        """
        url = urljoin(self.url, endpoint)
        if method is None:
            method = 'POST' if data is not None else 'GET'

        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }
        request_data = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(url, data=request_data, headers=headers, method=method)
        ssl_context = self._ssl_context()

        try:
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get('error', str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            raise ChelonClientError(f"HTTP {e.code}: {error_msg}")
        except urllib.error.URLError as e:
            raise ChelonClientError(f"Connection error: {e.reason}")
        except Exception as e:
            raise ChelonClientError(f"Request failed: {e}")

    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make authenticated POST request to Chelon API (signing endpoints)."""
        return self._http_request(endpoint, data=data, method='POST')
    
    def list_keys(self) -> list:
        """Return configured signing keys from GET /api/v1/keys."""
        response = self._http_request('/api/v1/keys', method='GET')
        if 'error' in response:
            raise ChelonClientError(f"Failed to list keys: {response['error']}")
        return response.get('keys') or []

    def get_key_backend(self, key_name: str) -> Optional[str]:
        """
        Resolve the signing backend for a key alias or key ID.

        Returns:
            'gpg', 'sequoia', or None if the key is not listed.
        """
        if not key_name:
            return None
        needle = key_name.upper()
        for entry in self.list_keys():
            alias = str(entry.get('type') or entry.get('name') or '')
            key_id = str(entry.get('key_id') or '')
            fingerprint = str(entry.get('fingerprint') or '')
            if (
                alias == key_name
                or key_id.upper() == needle
                or fingerprint.upper() == needle
            ):
                return (entry.get('backend') or 'gpg').lower()
        return None

    def sign_data(self, data: bytes, key_type: Optional[str] = None, operation: str = 'rpm') -> Dict[str, Any]:
        """
        Sign arbitrary data
        
        Args:
            data: Data to sign (will be base64 encoded)
            key_type: Optional name or ID of the key to use (defaults to server default)
            operation: Operation type ('rpm' or 'repodata')
            
        Returns:
            Dict with 'signature', 'key_id', 'key_fingerprint', 'request_id', 'timestamp'
            
        Raises:
            ChelonClientError: On signing failure
        """
        # Encode data
        encoded_data = base64.b64encode(data).decode('ascii')
        
        # Prepare request
        payload = {
            'data': encoded_data
        }
        if key_type:
            payload['key_type'] = key_type
        
        # Make request
        endpoint = f'/api/v1/sign/{operation}'
        response = self._make_request(endpoint, payload)
        
        # Check for errors
        if 'error' in response:
            raise ChelonClientError(f"Signing failed: {response['error']}")
        
        return response
    
    def sign_file(self, file_path: str, key_type: Optional[str] = None, operation: str = 'rpm') -> Dict[str, Any]:
        """
        Sign a file
        
        Args:
            file_path: Path to file to sign
            key_type: Optional key type/ID to use
            operation: Operation type
            
        Returns:
            Signing response dict
        """
        with open(file_path, 'rb') as f:
            data = f.read()
        
        return self.sign_data(data, key_type, operation)


def get_client(**kwargs) -> ChelonClient:
    """
    Get a configured Chelon client
    
    Args:
        **kwargs: Arguments to pass to ChelonClient constructor
        
    Returns:
        Configured ChelonClient instance
    """
    return ChelonClient(**kwargs)


if __name__ == '__main__':
    # Simple test
    try:
        client = get_client()
        print(f"Chelon client initialized successfully")
        print(f"  URL: {client.url}")
        print(f"  Cert dir: {client.cert_dir}")
    except ChelonClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
