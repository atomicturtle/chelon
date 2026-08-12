
import os
import sys
import unittest
import tempfile
import json
import importlib.util
from unittest.mock import MagicMock, patch

# Add server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../server'))

# Mock dependencies to avoid import errors (gnupg, etc)
# We need to mock them BEFORE loading chelon_service
sys.modules['signing_engine'] = MagicMock()
sys.modules['auth'] = MagicMock()
sys.modules['audit'] = MagicMock()
sys.modules['gnupg'] = MagicMock()

class TestConfigSecurity(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'chelon.conf')
        with open(self.config_path, 'w') as f:
            f.write("LEGACY_PASSPHRASE=secret\n")
        
        # Set environment
        os.environ['CHELON_CONFIG'] = self.config_path
        
        # Path to service file
        self.service_path = os.path.join(os.path.dirname(__file__), '../server/chelon-service.py')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
        # Clean up sys.modules to ensure fresh import each time if needed, 
        # though we are manually loading it.
        if "chelon_service" in sys.modules:
            del sys.modules["chelon_service"]
        for name in ("signing_engine", "auth", "audit", "gnupg"):
            mod = sys.modules.get(name)
            if mod is not None and isinstance(mod, MagicMock):
                del sys.modules[name]

    def load_service_module(self):
        spec = importlib.util.spec_from_file_location("chelon_service", self.service_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["chelon_service"] = module
        spec.loader.exec_module(module)
        return module

    @patch('os.stat')
    @patch('sys.exit')
    def test_insecure_permissions(self, mock_exit, mock_stat):
        # Mock world-readable permissions (0o644 -> world read is 0o004)
        mock_stat.return_value.st_mode = 0o100644
        
        # Checking if import triggers exit
        try:
             self.load_service_module()
        except Exception as exc:
            self.fail(f"Unexpected exception during service module load: {exc}")
            
        # Should call exit(1) during module load
        mock_exit.assert_called_with(1)

    @patch('os.stat')
    @patch('sys.exit')
    def test_secure_permissions(self, mock_exit, mock_stat):
        # Mock secure permissions (0o600)
        mock_stat.return_value.st_mode = 0o100600
        
        module = self.load_service_module()
        
        # Should NOT call exit
        mock_exit.assert_not_called()
        
        # Config should be loaded
        self.assertTrue(module.config)

    @patch('os.stat')
    def test_payload_size_limit(self, mock_stat):
        # Mock secure permissions so module loads
        mock_stat.return_value.st_mode = 0o100600
        
        module = self.load_service_module()
        
        # Mock token auth to bypass authentication
        module.token_auth = MagicMock()
        module.token_auth.validate_token.return_value = {
            'token_id': 'test',
            'permissions': ['sign:rpm']
        }
        
        # Create request context
        app = module.app
        with app.test_request_context(
            '/api/v1/sign/rpm',
            method='POST',
            json={'data': 'A' * (10 * 1024 * 1024 + 1)}, # 10MB + 1 byte
            headers={'Authorization': 'Bearer test_token'}
        ):
            # The service calls request.get_json(), which we mocked via test_request_context json arg
            response, status = module._handle_signing('sign_rpm')
            self.assertEqual(status, 413)
            self.assertIn('Payload too large', response.json['error'])

if __name__ == '__main__':
    unittest.main()
