
import sys
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

# Add server to path
sys.path.insert(0, '/home/sshinn/src/chelon/server')

from auth import TokenAuth

class TestRateLimit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, 'chelon.conf')
        self.tokens_file = os.path.join(self.temp_dir, 'tokens.json')
        
        # Mock paths in TokenAuth
        self.auth_patcher = patch('auth.Path')
        self.mock_path = self.auth_patcher.start()
        
        # We need to make sure tokens_file path resolves to our temp file
        # This is scanning for calls to Path('/var/lib/chelon/tokens.json')
        # Easier way: subclass or just patch the attributes after init if possible,
        # but init loads tokens.
        
        with open(self.config_file, 'w') as f:
            f.write("TEST=1\n")
            
    def tearDown(self):
        self.auth_patcher.stop()
        shutil.rmtree(self.temp_dir)

    def test_rate_limit_window(self):
        # We'll just patch the tokens file attribute and load_tokens method to avoid filesystem issues
        # effectively testing the logic in validate_token
        
        with patch('auth.TokenAuth._load_tokens', return_value={}) as mock_load, \
             patch('auth.TokenAuth._save_tokens'):
            
            auth = TokenAuth(self.config_file)
            
            # Manually inject a token
            token_id = "test-token"
            secret = "secret"
            import hashlib
            secret_hash = hashlib.sha256(secret.encode()).hexdigest()
            
            auth.tokens = {
                token_id: {
                    'secret_hash': secret_hash,
                    'permissions': ['sign:rpm'],
                    'rate_limit': 2,
                    'created': datetime.now(timezone.utc).isoformat(),
                    'last_used': None
                }
            }
            
            token_str = f"{token_id}:{secret}"
            
            # Start time: T=0
            start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
            
            with patch('auth.datetime') as mock_datetime:
                mock_datetime.now.return_value = start_time
                
                # Request 1 (Count: 1) - Should succeed
                print("Request 1...")
                auth.validate_token(token_str)
                
                # Request 2 (Count: 2) - Should succeed
                print("Request 2...")
                auth.validate_token(token_str)
                
                # Request 3 (Count: 3 > Limit 2) - Should fail
                print("Request 3 (Should fail)...")
                with self.assertRaises(ValueError) as cm:
                    auth.validate_token(token_str)
                self.assertEqual(str(cm.exception), "Rate limit exceeded")
                
                # Advance time by 30 mins (Still in window)
                mock_datetime.now.return_value = start_time + timedelta(minutes=30)
                
                # Request 4 (Should still fail)
                print("Request 4 (30m later, Should fail)...")
                with self.assertRaises(ValueError) as cm:
                    auth.validate_token(token_str)
                
                # Advance time by 61 mins (New window)
                mock_datetime.now.return_value = start_time + timedelta(minutes=61)
                
                # Request 5 (Reset count: 1) - Should succeed
                print("Request 5 (1h+ later, Should succeed)...")
                auth.validate_token(token_str)
                
                print("Rate limit test passed!")

if __name__ == '__main__':
    unittest.main()
