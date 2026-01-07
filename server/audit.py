"""
Audit logging for Chelon
Tracks all signing operations for security and compliance
"""

import json
import logging
from datetime import datetime, UTC
from pathlib import Path

logger = logging.getLogger(__name__)


class AuditLogger:
    """Audit logging for signing operations"""
    
    def __init__(self, config_file: str = None, log_dir: str = None):
        """Initialize audit logger"""
        # We use a specific logger for audit events so they can be filtered
        self.logger = logging.getLogger('chelon.audit')
        self.logger.info("Audit logger initialized (logging to journald/syslog)")
    
    def log_signing(self, token_id: str, operation: str, key_used: str,
                    data_hash: str, success: bool, client_ip: str,
                    request_id: str = None, latency: float = None,
                    key_fingerprint: str = None, payload_size: int = None,
                    error: str = None):
        """
        Log a signing operation
        
        Args:
            token_id: ID of the token used
            operation: Operation type ('sign_rpm', 'sign_repodata')
            key_used: GPG key ID used
            data_hash: Hash of data signed
            success: Whether operation succeeded
            client_ip: Client IP address
            request_id: Unique request ID
            latency: Processing time in seconds
            key_fingerprint: Full GPG key fingerprint
            payload_size: Size of payload in bytes
            error: Error message if failed
        """
        log_entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'request_id': request_id,
            'token_id': token_id,
            'operation': operation,
            'key_used': key_used,
            'key_fingerprint': key_fingerprint,
            'data_hash': data_hash,
            'payload_size': payload_size,
            'latency': latency,
            'success': success,
            'client_ip': client_ip
        }
        
        if error:
            log_entry['error'] = error
        
        # Log to standard logging system with a prefix for easy grep
        # Using comma separator for prefix to make it robust
        self.logger.info(f"AUDIT_ENTRY: {json.dumps(log_entry)}")
    
    def get_recent_logs(self, limit: int = 100) -> list:
        """
        Get recent audit log entries
        Deprecated for direct file access. Returns empty list.
        Consumers should use journalctl.
        """
        # This function is now deprecated in favor of journalctl
        # We return empty here to avoid breaking callers instantly, 
        # but the admin tool will be updated to fetch from journal.
        self.logger.warning(
            "AuditLogger.get_recent_logs is deprecated and returns an empty list; "
            "use journalctl to access audit logs instead."
        )
        return []
