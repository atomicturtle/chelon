
import sys
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Add server to path
sys.path.insert(0, '/usr/share/chelon/server')

from signing_engine import SigningEngine
import gnupg

class TestSigningFix(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.gpg_home = os.path.join(self.temp_dir, '.gnupg')
        os.makedirs(self.gpg_home, mode=0o700)
        self.gpg = gnupg.GPG(gnupghome=self.gpg_home)
        
        # Generate a key
        input_data = self.gpg.gen_key_input(
            key_type="RSA",
            key_length=1024,
            name_real="Test Key",
            name_email="test@example.com",
            no_protection=True
        )
        self.key = self.gpg.gen_key(input_data)
        self.key_id = self.key.fingerprint[-8:] # Get short ID
        
        print(f"Generated test key: {self.key_id}")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_sign_binary_data(self):
        engine = SigningEngine(gnupg_home=self.gpg_home)
        
        # Monkeypatch keys to use our test key
        with patch.dict(engine.KEYS, {'modern': self.key_id, 'legacy': '00000000'}, clear=True):
            data = b"Hello, World! This is binary data."
            
            # Sign
            signature = engine.sign_data(data, 'modern')
            
            print(f"Signature generated:\n{signature}")
            
            # Write sig and data to temp files for robust verification
            sig_path = os.path.join(self.temp_dir, 'sig.asc')
            data_path = os.path.join(self.temp_dir, 'data.bin')
            
            with open(sig_path, 'w') as f:
                f.write(signature)
            with open(data_path, 'wb') as f:
                f.write(data)
                
            # Verify using file-based method
            with open(sig_path, 'rb') as f:
                verified = self.gpg.verify_file(f, data_path)
            
            if not verified.valid:
                print(f"Verification failed!")
                print(f"Status: {verified.status}")
                print(f"Problems: {verified.problems}")
                print(f"Stderr:\n{verified.stderr}")
            self.assertTrue(verified.valid)
            self.assertEqual(verified.key_id, self.key.fingerprint[-16:]) # python-gnupg returns 16 char ID often
            
            print("Verification successful!")

if __name__ == '__main__':
    unittest.main()
