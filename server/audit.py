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
    
    def __init__(self, log_dir: str = '/var/lib/chelon'):
        """Initialize audit logger"""
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file = self.log_dir / 'audit.log'
        logger.info(f"Audit logging to: {self.audit_file}")
    
    def log_signing(self, token_id: str, operation: str, key_used: str,
                    data_hash: str, success: bool, client_ip: str,
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
            error: Error message if failed
        """
        log_entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'token_id': token_id,
            'operation': operation,
            'key_used': key_used,
            'data_hash': data_hash,
            'success': success,
            'client_ip': client_ip
        }
        
        if error:
            log_entry['error'] = error
        
        # Write to audit log
        try:
            with open(self.audit_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def get_recent_logs(self, limit: int = 100) -> list:
        """Get recent audit log entries"""
        if not self.audit_file.exists():
            return []
        
        logs = []
        try:
            with open(self.audit_file, 'r') as f:
                for line in f:
                    logs.append(json.loads(line.strip()))
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")
        
        return logs[-limit:]
