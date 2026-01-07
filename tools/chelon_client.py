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
        self.client_cert = self.cert_dir / 'client.crt'
        self.client_key = self.cert_dir / 'client.key'
        self.ca_cert = self.cert_dir / 'ca.crt'
        
        if not self.client_cert.exists():
            raise ChelonClientError(f"Client certificate not found: {self.client_cert}")
        if not self.client_key.exists():
            raise ChelonClientError(f"Client key not found: {self.client_key}")
        if self.verify_ssl and not self.ca_cert.exists():
            raise ChelonClientError(f"CA certificate not found: {self.ca_cert}")
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make authenticated request to Chelon API
        
        Args:
            endpoint: API endpoint (e.g., '/api/v1/sign/rpm')
            data: Request payload
            
        Returns:
            Response data as dict
            
        Raises:
            ChelonClientError: On request failure
        """
        url = urljoin(self.url, endpoint)
        
        # Prepare request
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        request_data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=request_data, headers=headers, method='POST')
        
        # Setup SSL context
        if self.verify_ssl:
            # When verifying SSL, ensure the provided CA certificate file exists before using it
            ca_cert_path = Path(self.ca_cert) if not isinstance(self.ca_cert, Path) else self.ca_cert
            if not ca_cert_path.is_file():
                raise ChelonClientError(f"CA certificate file not found: {ca_cert_path}")
            ssl_context = ssl.create_default_context(cafile=str(ca_cert_path))
        else:
            # When not verifying SSL, do not load a CA file
            ssl_context = ssl.create_default_context()
        
        ssl_context.load_cert_chain(certfile=str(self.client_cert), keyfile=str(self.client_key))
        
        if not self.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        # Make request
        try:
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
                response_data = json.loads(response.read().decode('utf-8'))
                return response_data
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
    
    def sign_data(self, data: bytes, key_type: str = 'modern', operation: str = 'rpm') -> Dict[str, Any]:
        """
        Sign arbitrary data
        
        Args:
            data: Data to sign (will be base64 encoded)
            key_type: Key type to use ('legacy' or 'modern')
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
            'data': encoded_data,
            'key_type': key_type
        }
        
        # Make request
        endpoint = f'/api/v1/sign/{operation}'
        response = self._make_request(endpoint, payload)
        
        # Check for errors
        if 'error' in response:
            raise ChelonClientError(f"Signing failed: {response['error']}")
        
        return response
    
    def sign_file(self, file_path: str, key_type: str = 'modern', operation: str = 'rpm') -> Dict[str, Any]:
        """
        Sign a file
        
        Args:
            file_path: Path to file to sign
            key_type: Key type to use
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
