"""
Chelon - Remote GPG Signing Service
Flask API for signing RPM packages and repository metadata
"""

import os
import sys
import json
import logging
from datetime import datetime, UTC
from flask import Flask, request, jsonify
from pathlib import Path
import base64

# Import our modules
from signing_engine import SigningEngine
from auth import TokenAuth
from audit import AuditLogger

app = Flask(__name__)

# Configuration
CONFIG_FILE = os.environ.get('ORACLE_CONFIG', '/etc/chelon/chelon.conf')
DATA_DIR = '/var/lib/chelon'

def load_config(path):
    """Load simple key-value config file"""
    config = {}
    if not os.path.exists(path):
        return config
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    config[k.strip()] = v.strip()
    except Exception as e:
        print(f"Error loading config: {e}")
    return config

# Initialize components
config = load_config(CONFIG_FILE)
# Log config status
lp = config.get('LEGACY_PASSPHRASE')
mp = config.get('MODERN_PASSPHRASE')
print(f"DEBUG: Config loaded. Legacy PP len: {len(lp) if lp else 0}, Modern PP len: {len(mp) if mp else 0}")

signing_engine = SigningEngine()
token_auth = TokenAuth(config_file=CONFIG_FILE)
audit_logger = AuditLogger()

# Setup logging (stdout only - journald will capture it)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def _handle_signing(operation):
    """Common signing logic for both RPMs and repodata"""
    # Authenticate request
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid authorization header'}), 401
    
    token = auth_header.split(' ', 1)[1]
    
    try:
        token_info = token_auth.validate_token(token)
    except Exception as e:
        logger.warning(f"Authentication failed: {e}")
        return jsonify({'error': 'Invalid token'}), 401
    
    # Check permissions
    required_perm = f'sign:{operation.split("_")[1]}'
    if required_perm not in token_info.get('permissions', []):
        logger.warning(f"Token {token_info.get('token_id')} lacks {required_perm}")
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    # Parse request
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    raw_data_b64 = data.get('data') 
    package_hash = data.get('package_hash')
    repodata_hash = data.get('repodata_hash')
    key_type = data.get('key_type', 'legacy')
    
    sign_target = None
    data_id = None

    if raw_data_b64:
        try:
            sign_target = base64.b64decode(raw_data_b64)
            data_id = f"raw_data:{len(sign_target)}b"
        except Exception as e:
            return jsonify({'error': f'Invalid Base64 data: {e}'}), 400
    elif package_hash:
        sign_target = package_hash
        data_id = package_hash
    elif repodata_hash:
        sign_target = repodata_hash
        data_id = repodata_hash
    else:
        return jsonify({'error': 'Missing signing target (data, package_hash, or repodata_hash)'}), 400
    
    # Sign the data
    try:
        passphrase = config.get('MODERN_PASSPHRASE' if key_type == 'modern' else 'LEGACY_PASSPHRASE')
        signature = signing_engine.sign_data(sign_target, key_type, passphrase)
        key_id = signing_engine.get_key_id(key_type)
        
        # Audit log
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=key_id,
            data_hash=data_id,
            success=True,
            client_ip=request.remote_addr
        )
        
        return jsonify({
            'signature': signature,
            'key_id': key_id,
            'timestamp': datetime.now(UTC).isoformat()
        })
    
    except Exception as e:
        logger.error(f"Signing failed: {e}")
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=key_id if 'key_id' in locals() else key_type,
            data_hash=data_id,
            success=False,
            client_ip=request.remote_addr,
            error=str(e)
        )
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'timestamp': datetime.now(UTC).isoformat()
    })


@app.route('/api/v1/keys', methods=['GET'])
def list_keys():
    """List available signing keys"""
    try:
        keys = signing_engine.list_keys()
        return jsonify({
            'keys': keys,
            'timestamp': datetime.now(UTC).isoformat()
        })
    except Exception as e:
        logger.error(f"Error listing keys: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/sign/rpm', methods=['POST'])
def sign_rpm():
    """Sign RPM package headers"""
    return _handle_signing('sign_rpm')


@app.route('/api/v1/sign/repodata', methods=['POST'])
def sign_repodata():
    """Sign repository metadata"""
    return _handle_signing('sign_repodata')


if __name__ == '__main__':
    # Run the Flask app
    host = os.environ.get('ORACLE_HOST', '127.0.0.1')
    port = int(os.environ.get('ORACLE_PORT', 5050))

    logger.info(f"Starting Chelon service on {host}:{port}")
    app.run(host=host, port=port, debug=False)
