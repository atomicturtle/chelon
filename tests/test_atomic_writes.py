"""
Tests for atomic file write operations in TokenAuth
"""

import os
import sys
import unittest
from unittest.mock import MagicMock
import tempfile
import json
import threading
import time
from pathlib import Path

# Add server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../server'))

# Mock gnupg before importing modules
sys.modules['gnupg'] = MagicMock()

from auth import TokenAuth


class TestAtomicWrites(unittest.TestCase):
    """Test atomic file write operations for token storage"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / 'data'
        self.data_dir.mkdir()
        self.tokens_file = self.data_dir / 'tokens.json'
        
        # Don't use a config file to avoid ownership checks in tests
        # Instead, directly manipulate the auth instance
        from unittest.mock import patch
        
        # Create instance without config file (avoids ownership checks)
        with patch.object(Path, 'exists', return_value=False):
            self.auth = TokenAuth(config_file='/nonexistent')
        
        # Override the tokens_file path to use our test directory
        self.auth.tokens_file = self.tokens_file
        self.auth.tokens = {}
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_atomic_write_creates_file(self):
        """Test that atomic write successfully creates token file"""
        token = self.auth.generate_token('test-token', ['sign:rpm'], rate_limit=100)
        
        self.assertTrue(self.tokens_file.exists())
        self.assertIsNotNone(token)
    
    def test_atomic_write_preserves_permissions(self):
        """Test that atomic write maintains 0600 permissions"""
        self.auth.generate_token('test-token', ['sign:rpm'], rate_limit=100)
        
        stat_info = self.tokens_file.stat()
        mode = oct(stat_info.st_mode)[-3:]
        
        self.assertEqual(mode, '600', 'Token file should have 0600 permissions')
    
    def test_atomic_write_no_temp_files_left(self):
        """Test that atomic write doesn't leave temporary files"""
        self.auth.generate_token('test-token', ['sign:rpm'], rate_limit=100)
        
        # Check for any .tokens.json.*.tmp files
        temp_files = list(self.data_dir.glob('.tokens.json.*'))
        
        self.assertEqual(len(temp_files), 0, 'No temporary files should remain')
    
    def test_atomic_write_data_integrity(self):
        """Test that written data can be read back correctly"""
        token = self.auth.generate_token('test-token', ['sign:rpm', 'sign:repodata'], rate_limit=50)
        
        # Read file directly
        with open(self.tokens_file) as f:
            data = json.load(f)
        
        self.assertIn('test-token', data)
        self.assertEqual(data['test-token']['permissions'], ['sign:rpm', 'sign:repodata'])
        self.assertEqual(data['test-token']['rate_limit'], 50)
        self.assertIn('secret_hash', data['test-token'])
        self.assertIn('created', data['test-token'])
    
    def test_atomic_write_concurrent_safety(self):
        """Test that concurrent writes don't corrupt the file"""
        errors = []
        
        def generate_token(token_id):
            try:
                self.auth.generate_token(f'token-{token_id}', ['sign:rpm'], rate_limit=100)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads generating tokens simultaneously
        threads = []
        for i in range(10):
            t = threading.Thread(target=generate_token, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f'Concurrent writes should not error: {errors}')
        
        # Verify file is valid JSON and contains all tokens
        with open(self.tokens_file) as f:
            data = json.load(f)
        
        self.assertEqual(len(data), 10, 'All 10 tokens should be present')
        for i in range(10):
            self.assertIn(f'token-{i}', data)
    
    def test_atomic_write_failure_cleanup(self):
        """Test that temp files are cleaned up on write failure"""
        # Force a write failure by making directory read-only after first write
        self.auth.generate_token('initial-token', ['sign:rpm'], rate_limit=100)
        
        # Make directory read-only
        self.data_dir.chmod(0o500)
        
        try:
            # This should fail due to permissions
            self.auth.generate_token('fail-token', ['sign:rpm'], rate_limit=100)
        except Exception:
            pass  # Expected to fail
        
        # Restore permissions to check for temp files
        self.data_dir.chmod(0o700)
        
        # Verify no temp files were left behind
        temp_files = list(self.data_dir.glob('.tokens.json.*'))
        self.assertEqual(len(temp_files), 0, 'Temp files should be cleaned up on error')
    
    def test_multiple_writes_preserve_data(self):
        """Test that multiple writes don't lose previous data"""
        # Generate several tokens
        self.auth.generate_token('token-1', ['sign:rpm'], rate_limit=100)
        self.auth.generate_token('token-2', ['sign:repodata'], rate_limit=200)
        self.auth.generate_token('token-3', ['sign:rpm', 'sign:repodata'], rate_limit=150)
        
        # Read and verify all tokens exist
        with open(self.tokens_file) as f:
            data = json.load(f)
        
        self.assertEqual(len(data), 3)
        self.assertIn('token-1', data)
        self.assertIn('token-2', data)
        self.assertIn('token-3', data)
        
        # Verify individual token data
        self.assertEqual(data['token-1']['rate_limit'], 100)
        self.assertEqual(data['token-2']['rate_limit'], 200)
        self.assertEqual(data['token-3']['rate_limit'], 150)
    
    def test_revoke_token_atomic_write(self):
        """Test that token revocation also uses atomic writes"""
        self.auth.generate_token('token-to-revoke', ['sign:rpm'], rate_limit=100)
        self.auth.generate_token('token-to-keep', ['sign:rpm'], rate_limit=100)
        
        # Revoke one token
        self.auth.revoke_token('token-to-revoke')
        
        # Verify file integrity
        with open(self.tokens_file) as f:
            data = json.load(f)
        
        self.assertNotIn('token-to-revoke', data)
        self.assertIn('token-to-keep', data)
        
        # Verify no temp files
        temp_files = list(self.data_dir.glob('.tokens.json.*'))
        self.assertEqual(len(temp_files), 0)
    
    def test_temp_file_permissions(self):
        """Test that temporary files are created with correct permissions before rename"""
        from unittest.mock import patch
        import pwd
        import grp
        
        captured_temp_perms = {}
        original_rename = os.rename
        
        def capture_perms_before_rename(src, dst):
            """Capture temp file permissions before rename"""
            if '.tokens.json.' in src and src.endswith('.tmp'):
                stat_info = Path(src).stat()
                captured_temp_perms['mode'] = oct(stat_info.st_mode)[-3:]
                captured_temp_perms['uid'] = stat_info.st_uid
                captured_temp_perms['gid'] = stat_info.st_gid
            return original_rename(src, dst)
        
        with patch('os.rename', side_effect=capture_perms_before_rename):
            self.auth.generate_token('test-token', ['sign:rpm'], rate_limit=100)
        
        # Verify temp file had correct permissions before rename
        self.assertEqual(captured_temp_perms['mode'], '600', 
                        'Temp file should have 0600 permissions before rename')
        self.assertEqual(captured_temp_perms['uid'], os.getuid(),
                        'Temp file should have correct UID')
    
    def test_ownership_set_when_running_as_root(self):
        """Test that ownership is set correctly when running as root (mocked)"""
        from unittest.mock import patch, MagicMock
        import pwd
        import grp
        
        # Mock user/group lookups
        mock_pwd = MagicMock()
        mock_pwd.pw_uid = 999
        mock_grp = MagicMock()
        mock_grp.gr_gid = 999
        
        captured_chown_calls = []
        
        def capture_chown(path, uid, gid):
            """Capture chown calls"""
            captured_chown_calls.append({'path': path, 'uid': uid, 'gid': gid})
        
        # Mock running as root
        with patch('os.getuid', return_value=0), \
             patch('pwd.getpwnam', return_value=mock_pwd), \
             patch('grp.getgrnam', return_value=mock_grp), \
             patch('os.chown', side_effect=capture_chown):
            
            self.auth.generate_token('root-test-token', ['sign:rpm'], rate_limit=100)
        
        # Verify chown was called on the temp file
        self.assertEqual(len(captured_chown_calls), 1, 
                        'chown should be called once when running as root')
        self.assertEqual(captured_chown_calls[0]['uid'], 999,
                        'Should set UID to chelon user')
        self.assertEqual(captured_chown_calls[0]['gid'], 999,
                        'Should set GID to chelon group')
        
        # Verify the temp file path was chowned (not the final path)
        chowned_path = captured_chown_calls[0]['path']
        self.assertIn('.tokens.json.', chowned_path,
                     'Should chown temp file before rename')
        self.assertTrue(chowned_path.endswith('.tmp'),
                       'Should chown temp file, not final file')
    
    def test_atomic_rename_succeeds(self):
        """Test that the atomic rename operation completes successfully"""
        from unittest.mock import patch
        
        rename_calls = []
        original_rename = os.rename
        
        def track_rename(src, dst):
            """Track rename calls"""
            rename_calls.append({'src': src, 'dst': str(dst)})
            return original_rename(src, dst)
        
        with patch('os.rename', side_effect=track_rename):
            self.auth.generate_token('rename-test', ['sign:rpm'], rate_limit=100)
        
        # Verify rename was called
        self.assertEqual(len(rename_calls), 1, 'Rename should be called once')
        
        # Verify source was temp file
        src = rename_calls[0]['src']
        self.assertIn('.tokens.json.', src, 'Source should be temp file')
        self.assertTrue(src.endswith('.tmp'), 'Source should be .tmp file')
        
        # Verify destination is the actual tokens file
        dst = rename_calls[0]['dst']
        self.assertEqual(dst, str(self.tokens_file), 
                        'Destination should be tokens.json')
        
        # Verify final file exists and temp file doesn't
        self.assertTrue(self.tokens_file.exists(), 
                       'Final tokens.json should exist after rename')
        temp_files = list(self.data_dir.glob('.tokens.json.*'))
        self.assertEqual(len(temp_files), 0,
                        'No temp files should remain after successful rename')


if __name__ == '__main__':
    unittest.main()
