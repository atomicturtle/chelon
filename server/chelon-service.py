"""
Chelon - Remote GPG Signing Service
Flask API for signing RPM packages and repository metadata
"""

import os
import sys
import uuid
import time
import logging
import hashlib
from datetime import datetime, UTC
from flask import Flask, request, jsonify
import base64

# Import our modules
from signing_engine import SigningEngine
from auth import TokenAuth
from audit import AuditLogger

app = Flask(__name__)

# Setup logging (stdout only - journald will capture it)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG_FILE = os.environ.get('CHELON_CONFIG', '/etc/chelon/chelon.conf')
DATA_DIR = '/var/lib/chelon'

def load_config(path):
    """Load simple key-value config file"""
    config = {}
    if not os.path.exists(path):
        return config
    
    # Security check using stat
    try:
        st = os.stat(path)
        # Check for world access (read/write/execute)
        if st.st_mode & 0o007:
            logger.critical(f"Config file {path} is world-accessible ({oct(st.st_mode & 0o777)}).")
            logger.critical("Please secure it: chmod 600 or 640 " + path)
            sys.exit(1)
    except OSError as e:
        logger.error(f"Error checking config permissions: {e}")
        sys.exit(1)

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
        logger.error(f"Error loading config: {e}")
    return config

# Initialize components
config = load_config(CONFIG_FILE)
# Log config status
logger.info("Configuration loaded successfully")

signing_engine = SigningEngine()
token_auth = TokenAuth(config_file=CONFIG_FILE)
audit_logger = AuditLogger()


def _handle_signing(operation):
    """Common signing logic for both RPMs and repodata"""
    request_id = str(uuid.uuid4())
    start_time = time.time()
    
    # Authenticate request
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logger.warning(f"[{request_id}] Missing or invalid authorization header")
        return jsonify({'error': 'Missing or invalid authorization header', 'request_id': request_id}), 401
    
    token = auth_header.split(' ', 1)[1]
    
    try:
        token_info = token_auth.validate_token(token)
    except ValueError as e:
        latency = time.time() - start_time
        err_msg = str(e)
        status_code = 429 if "Rate limit" in err_msg else 401
        
        logger.warning(f"[{request_id}] Auth failure: {err_msg}")
        
        # Log auth failures (limit audit spam for unauthorized?)
        # For rate limits, we definitely want to audit
        if status_code == 429 or "Unknown token" not in err_msg:
             audit_logger.log_signing(
                token_id=getattr(token_auth, 'last_failed_token_id', 'unknown'), # We might not have ID
                operation=operation,
                key_used=None,
                data_hash=None,
                success=False,
                client_ip=request.remote_addr,
                request_id=request_id,
                latency=latency,
                error=err_msg
            )
        return jsonify({'error': err_msg, 'request_id': request_id}), status_code
    except Exception as e:
        logger.error(f"[{request_id}] Systematic auth error: {e}")
        return jsonify({'error': 'Authentication system error', 'request_id': request_id}), 500
    
    # Check permissions
    required_perm = f'sign:{operation.split("_")[1]}'
    if required_perm not in token_info.get('permissions', []):
        latency = time.time() - start_time
        logger.warning(f"[{request_id}] Token {token_info.get('token_id')} lacks {required_perm}")
        
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=None,
            data_hash=None,
            success=False,
            client_ip=request.remote_addr,
            request_id=request_id,
            latency=latency,
            error='Insufficient permissions'
        )
        return jsonify({'error': 'Insufficient permissions', 'request_id': request_id}), 403
    
    # Parse request
    try:
        data = request.get_json()
    except Exception:
        return jsonify({'error': 'Invalid JSON', 'request_id': request_id}), 400
        
    if not data:
        return jsonify({'error': 'Empty request body', 'request_id': request_id}), 400
    
    raw_data_b64 = data.get('data') 
    payload_size = len(raw_data_b64) if raw_data_b64 else 0
    
    # DoS Protection: Limit payload size
    if raw_data_b64 and payload_size > 10 * 1024 * 1024:  # 10MB limit
        latency = time.time() - start_time
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=None,
            data_hash=f"size:{payload_size}",
            success=False,
            client_ip=request.remote_addr,
            request_id=request_id,
            latency=latency,
            payload_size=payload_size,
            error='Payload too large'
        )
        return jsonify({'error': 'Payload too large (limit 10MB)', 'request_id': request_id}), 413

    if not raw_data_b64:
        return jsonify({'error': 'Missing "data" field', 'request_id': request_id}), 400
        
    key_type = data.get('key_type', 'legacy')
    
    sign_target = None
    data_id = None

    try:
        sign_target = base64.b64decode(raw_data_b64)
        data_id = hashlib.sha256(sign_target).hexdigest() # Properly hash the content for audit
    except Exception as e:
        return jsonify({'error': f'Invalid Base64 data: {e}', 'request_id': request_id}), 400
    
    # Sign the data
    try:
        passphrase = config.get('MODERN_PASSPHRASE' if key_type == 'modern' else 'LEGACY_PASSPHRASE')
        signature = signing_engine.sign_data(sign_target, key_type, passphrase)
        key_id = signing_engine.get_key_id(key_type)
        key_fingerprint = signing_engine.get_key_fingerprint(key_type)
        
        latency = time.time() - start_time
        
        # Audit log
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=key_id,
            data_hash=data_id,
            success=True,
            client_ip=request.remote_addr,
            request_id=request_id,
            latency=latency,
            key_fingerprint=key_fingerprint,
            payload_size=payload_size
        )
        
        return jsonify({
            'signature': signature,
            'key_id': key_id,
            'key_fingerprint': key_fingerprint,
            'request_id': request_id,
            'timestamp': datetime.now(UTC).isoformat()
        })
    
    except Exception as e:
        latency = time.time() - start_time
        logger.error(f"[{request_id}] Signing failed: {e}")
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=key_id if 'key_id' in locals() else key_type,
            data_hash=data_id,
            success=False,
            client_ip=request.remote_addr,
            request_id=request_id,
            latency=latency,
            error=str(e),
            payload_size=payload_size
        )
        return jsonify({'error': str(e), 'request_id': request_id}), 500


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
    host = os.environ.get('CHELON_HOST', '127.0.0.1')
    port = int(os.environ.get('CHELON_PORT', 5050))

    logger.info(f"Starting Chelon service on {host}:{port}")

    # SSL/TLS Configuration
    ssl_cert = os.environ.get('CHELON_SSL_CERT')
    ssl_key = os.environ.get('CHELON_SSL_KEY')
    ssl_ca = os.environ.get('CHELON_SSL_CA')
    verify_client = os.environ.get('CHELON_VERIFY_CLIENT', 'false').lower() == 'true'
    
    ssl_context = None
    if ssl_cert and ssl_key:
        if not os.path.exists(ssl_cert) or not os.path.exists(ssl_key):
            logger.error(f"SSL cert or key not found: {ssl_cert}, {ssl_key}")
            sys.exit(1)
        
        # If verify_client is True, ssl_ca must be provided
        if verify_client and not ssl_ca:
            logger.error("CHELON_VERIFY_CLIENT is True but CHELON_SSL_CA is not provided")
            logger.error("Cannot verify client certificates without a CA certificate")
            sys.exit(1)
        
        import ssl
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(ssl_cert, ssl_key)
        
        if ssl_ca:
            if not os.path.exists(ssl_ca):
                logger.error(f"SSL CA not found: {ssl_ca}")
                sys.exit(1)
            ssl_context.load_verify_locations(ssl_ca)
            if verify_client:
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                logger.info("mTLS enabled: Client certificate verification required")
            else:
                ssl_context.verify_mode = ssl.CERT_OPTIONAL
        logger.info(f"SSL Enabled. Client Verify: {verify_client}")
    
    app.run(host=host, port=port, debug=False, ssl_context=ssl_context)
