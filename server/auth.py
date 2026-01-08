"""
Token-based authentication for Chelon
"""

import os
import sys
import stat
import json
import logging
import hashlib
import secrets
import pwd
import grp
import threading
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class TokenAuth:
    """Token-based authentication manager"""
    
    def __init__(self, config_file: str = '/etc/chelon/chelon.conf'):
        """Initialize token auth"""
        self.config_file = Path(config_file)
        
        # Determine data directory from config
        data_dir = '/var/lib/chelon'
        if self.config_file.exists():
            # Security check: verify config file permissions and ownership
            try:
                file_stat = self.config_file.stat()
                mode = stat.S_IMODE(file_stat.st_mode)
                # Check for world access (read/write/execute)
                if mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH):
                    logger.critical(f"Config file {self.config_file} is world-accessible ({oct(mode)}). ")
                    logger.critical("Please secure it: chmod 600 or 640 " + str(self.config_file))
                    sys.exit(1)
                
                # Check ownership - should be owned by root or chelon user
                try:
                    chelon_uid = pwd.getpwnam('chelon').pw_uid
                except KeyError:
                    chelon_uid = None
                
                if file_stat.st_uid not in (0, chelon_uid) if chelon_uid else file_stat.st_uid != 0:
                    logger.critical(f"Config file {self.config_file} is owned by UID {file_stat.st_uid}, not root (0) or chelon user")
                    logger.critical("Please fix ownership: chown root:chelon " + str(self.config_file))
                    sys.exit(1)
            except Exception as e:
                logger.critical(f"Failed to perform security checks on config file {self.config_file}: {e}")
                sys.exit(1)

            try:
                with open(self.config_file, 'r') as f:
                    for line in f:
                        if line.strip().startswith('DATA_DIR='):
                            data_dir = line.split('=', 1)[1].strip()
            except Exception as e:
                logger.warning(f"Failed to read config {self.config_file}: {e}")
        
        self.tokens_file = Path(data_dir) / 'tokens.json'
        self.rate_limits = {}  # token_id -> {'count': int, 'window_start': float}
        self._lock = threading.Lock()
        
        # Load tokens
        self.tokens = self._load_tokens()
        logger.info(f"Loaded {len(self.tokens)} tokens from {self.tokens_file}")
    
    def _load_tokens(self) -> Dict:
        """Load tokens from file"""
        if not self.tokens_file.exists():
            logger.warning(f"Tokens file not found: {self.tokens_file}")
            return {}
        
        try:
            with open(self.tokens_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            return {}
    
    def _save_tokens(self):
        """Save tokens to file"""
        try:
            self.tokens_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.tokens_file, 'w') as f:
                json.dump(self.tokens, f, indent=2)
            # Secure permissions
            self.tokens_file.chmod(0o600)
            
            # If running as root, try to chown to chelon user
            if os.getuid() == 0:
                try:
                    uid = pwd.getpwnam('chelon').pw_uid
                    gid = grp.getgrnam('chelon').gr_gid
                    os.chown(self.tokens_file, uid, gid)
                except KeyError:
                    # User or group doesn't exist, ignore
                    pass
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
    
    def generate_token(self, token_id: str, permissions: list, rate_limit: int = 100) -> str:
        """
        Generate a new API token
        
        Args:
            token_id: Unique identifier for the token
            permissions: List of permissions (e.g., ['sign:rpm', 'sign:repodata'])
            rate_limit: Maximum requests per hour
        
        Returns:
            Full token string (token_id:secret)
        """
        # Generate random secret
        secret = secrets.token_urlsafe(48)
        
        # Store token info
        self.tokens[token_id] = {
            'secret_hash': hashlib.sha256(secret.encode()).hexdigest(),
            'permissions': permissions,
            'rate_limit': rate_limit,
            'created': datetime.now(UTC).isoformat(),
            'last_used': None
        }
        
        self._save_tokens()
        logger.info(f"Generated token: {token_id}")
        
        return f"{token_id}:{secret}"
    
    def validate_token(self, token: str) -> Dict:
        """
        Validate an API token
        
        Args:
            token: Full token string (token_id:secret)
        
        Returns:
            Token info dict
        
        Raises:
            ValueError: If token is invalid
        """
        # Parse token
        if ':' not in token:
            raise ValueError("Invalid token format")
        
        token_id, secret = token.split(':', 1)
        
        # Check if token exists, reload if not found (to handle new tokens without restart)
        if token_id not in self.tokens:
            with self._lock:
                # Double-check inside lock
                if token_id not in self.tokens:
                    logger.info(f"Token {token_id} not found in memory, reloading from {self.tokens_file}")
                    self.tokens = self._load_tokens()
            
        if token_id not in self.tokens:
            raise ValueError(f"Unknown token: {token_id}")
        
        token_info = self.tokens[token_id]
        
        # Verify secret
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        if not secrets.compare_digest(secret_hash, token_info['secret_hash']):
            raise ValueError("Invalid token secret")
        
        # Check rate limit (Fixed Window)
        now = datetime.now(UTC)
        window_size = 3600  # 1 hour in seconds
        
        with self._lock:
            limit_data = self.rate_limits.get(token_id, {
                'count': 0,
                'window_start': now.timestamp()
            })
            
            # Check if window has expired
            if now.timestamp() - limit_data['window_start'] > window_size:
                # Reset window
                limit_data = {
                    'count': 0,
                    'window_start': now.timestamp()
                }
            
            if limit_data['count'] >= token_info['rate_limit']:
                raise ValueError("Rate limit exceeded")
            
            # Increment request count
            limit_data['count'] += 1
            self.rate_limits[token_id] = limit_data
        
        # Update last used timestamp
        token_info['last_used'] = datetime.now(UTC).isoformat()
        self._save_tokens()
        
        return {
            'token_id': token_id,
            'permissions': token_info['permissions'],
            'rate_limit': token_info['rate_limit']
        }
    
    def revoke_token(self, token_id: str):
        """Revoke a token"""
        if token_id in self.tokens:
            del self.tokens[token_id]
            self._save_tokens()
            logger.info(f"Revoked token: {token_id}")
        else:
            logger.warning(f"Token not found: {token_id}")
    
    def list_tokens(self) -> list:
        """List all tokens (without secrets)"""
        return [
            {
                'token_id': token_id,
                'permissions': info['permissions'],
                'created': info['created'],
                'last_used': info.get('last_used')
            }
            for token_id, info in self.tokens.items()
        ]
