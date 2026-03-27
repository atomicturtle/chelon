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

DEFAULT_MAX_PAYLOAD_BYTES = 50 * 1024 * 1024

def _max_payload_bytes_from_config() -> int:
    """Return configured payload limit, with safe fallback."""
    raw = config.get('MAX_PAYLOAD_BYTES', str(DEFAULT_MAX_PAYLOAD_BYTES))
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError("MAX_PAYLOAD_BYTES must be > 0")
        return value
    except Exception:
        logger.warning(
            "Invalid MAX_PAYLOAD_BYTES value '%s'; using default %d",
            raw, DEFAULT_MAX_PAYLOAD_BYTES
        )
        return DEFAULT_MAX_PAYLOAD_BYTES

# Determine data directory
data_dir = config.get('DATA_DIR', '/var/lib/chelon')
keys_file = os.path.join(data_dir, 'keys.json')

signing_engine = SigningEngine(keys_file=keys_file)
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
    
    # Extract token_id from token string before validation for audit logging
    # Token format is "token_id:secret"
    token_id = None
    if token and ':' in token:
        token_id = token.split(':', 1)[0]
    
    try:
        token_info = token_auth.validate_token(token)
    except ValueError as e:
        latency = time.time() - start_time
        err_msg = str(e)
        status_code = 429 if "Rate limit" in err_msg else 401
        
        logger.warning(f"[{request_id}] Auth failure: {err_msg}")
        
        # Use extracted token_id if available, otherwise hash the token for audit trail
        if not token_id:
            token_id = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16] if token else 'empty'
        
        # Log auth failures (limit audit spam for unauthorized?)
        # For rate limits, we definitely want to audit
        if status_code == 429 or "Unknown token" not in err_msg:
             audit_logger.log_signing(
                token_id=token_id,
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
    except Exception as e:
        logger.error(f"[{request_id}] Invalid JSON: {e}")
        return jsonify({'error': 'Invalid JSON', 'request_id': request_id}), 400
    
    if not data:
        return jsonify({'error': 'Empty request body', 'request_id': request_id}), 400
    
    raw_data_b64 = data.get('data')
    
    max_payload_bytes = _max_payload_bytes_from_config()
    max_base64_bytes = ((max_payload_bytes + 2) // 3) * 4

    # DoS Protection: Check base64 string size BEFORE decoding to prevent memory exhaustion
    if raw_data_b64:
        base64_size = len(raw_data_b64)
        if base64_size > max_base64_bytes:
            latency = time.time() - start_time
            audit_logger.log_signing(
                token_id=token_info['token_id'],
                operation=operation,
                key_used=None,
                data_hash=f"size:{base64_size}",
                success=False,
                client_ip=request.remote_addr,
                request_id=request_id,
                latency=latency,
                payload_size=base64_size,
                error='Payload too large (pre-decode check)'
            )
            return jsonify({
                'error': f'Payload too large (base64 size exceeds limit: {max_base64_bytes} bytes)',
                'request_id': request_id
            }), 413
    
    # Decode and validate payload
    try:
        if not raw_data_b64:
            raise ValueError("Missing 'data' field")
        raw_data = base64.b64decode(raw_data_b64)
    except Exception as e:
        logger.error(f"[{request_id}] Failed to decode data: {e}")
        latency = time.time() - start_time
        audit_logger.log_signing(
            token_id=token_info['token_id'],
            operation=operation,
            key_used=None,
            data_hash=None,
            success=False,
            client_ip=request.remote_addr,
            request_id=request_id,
            latency=latency,
            error=f"Invalid base64 data: {str(e)}"
        )
        return jsonify({'error': f'Invalid base64 data: {str(e)}', 'request_id': request_id}), 400
    
    # Calculate actual decoded payload size
    payload_size = len(raw_data)
    
    # Secondary check: verify decoded size is within limit
    if payload_size > max_payload_bytes:
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
        return jsonify({
            'error': f'Payload too large (decoded size: {payload_size} bytes, limit: {max_payload_bytes} bytes)',
            'request_id': request_id
        }), 413

    # Resolve and validate Key ID
    # Default to the signing engine's default key if not specified
    key_type = data.get('key_type', signing_engine.default_key)
    try:
        resolved_key_id = signing_engine.get_key_id(key_type)
        resolved_key_name = signing_engine.get_key_name(key_type)
    except ValueError as e:
        logger.warning(f"[{request_id}] Invalid key_type or ID: {key_type} - {e}")
        return jsonify({
            'error': str(e),
            'request_id': request_id
        }), 400
    
    sign_target = None
    data_id = None

    # Reuse already-decoded payload instead of decoding again
    sign_target = raw_data
    data_id = hashlib.sha256(sign_target).hexdigest()  # Properly hash the content for audit
    
    # Sign the data
    try:
        # Resolve which passphrase to use based on target Key Name.
        # We look for SIGNING_KEY_<NAME>_PASSPHRASE in the config.
        # Fallback to LEGACY_PASSPHRASE / MODERN_PASSPHRASE only for backward compatibility if configured that way.
        passphrase_key = f"SIGNING_KEY_{resolved_key_name.upper()}_PASSPHRASE"
        passphrase = config.get(passphrase_key)
        
        # Backward compatibility fallback
        if not passphrase:
             if resolved_key_name == 'modern':
                 passphrase = config.get('MODERN_PASSPHRASE')
             elif resolved_key_name == 'legacy':
                 passphrase = config.get('LEGACY_PASSPHRASE')

        signature = signing_engine.sign_data(sign_target, resolved_key_id, passphrase)
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
    # Prioritize config file over environment variables
    host = config.get('CHELON_HOST') or os.environ.get('CHELON_HOST', '127.0.0.1')
    port = int(config.get('CHELON_PORT') or os.environ.get('CHELON_PORT') or 5050)

    logger.info(f"Starting Chelon service on {host}:{port}")

    # SSL/TLS Configuration - Prefer config file, fall back to environment
    ssl_cert = config.get('CHELON_SSL_CERT') or os.environ.get('CHELON_SSL_CERT')
    ssl_key = config.get('CHELON_SSL_KEY') or os.environ.get('CHELON_SSL_KEY')
    ssl_ca = config.get('CHELON_SSL_CA') or os.environ.get('CHELON_SSL_CA')
    
    # Support both names for backward compatibility/consistency
    # Precedence: config['CHELON_SSL_VERIFY_CLIENT'] > config['CHELON_VERIFY_CLIENT'] > env['CHELON_VERIFY_CLIENT']
    verify_client_val = (config.get('CHELON_SSL_VERIFY_CLIENT') or 
                         config.get('CHELON_VERIFY_CLIENT') or 
                         os.environ.get('CHELON_VERIFY_CLIENT', 'false'))
    verify_client = str(verify_client_val).lower() == 'true'
    
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
