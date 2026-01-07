
import os
import sys
import time
import subprocess
import unittest
import shutil
import tempfile
import requests
import signal
from pathlib import Path

# Add server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../server'))

# Generate certificates via openssl
def generate_certs(base_dir):
    # configured for localhost
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", 
        "-keyout", f"{base_dir}/ca.key", 
        "-out", f"{base_dir}/ca.crt", 
        "-days", "1", "-nodes", "-subj", "/CN=Test CA"
    ]
    subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
    
    # Server request
    subprocess.check_call([
        "openssl", "req", "-newkey", "rsa:2048", 
        "-keyout", f"{base_dir}/server.key", 
        "-out", f"{base_dir}/server.csr", 
        "-nodes", "-subj", "/CN=localhost"
    ], stderr=subprocess.DEVNULL)
    
    # Sign server
    subprocess.check_call([
        "openssl", "x509", "-req", 
        "-in", f"{base_dir}/server.csr", 
        "-CA", f"{base_dir}/ca.crt", 
        "-CAkey", f"{base_dir}/ca.key", 
        "-CAcreateserial", 
        "-out", f"{base_dir}/server.crt", 
        "-days", "1"
    ], stderr=subprocess.DEVNULL)
    
    # Client request
    subprocess.check_call([
        "openssl", "req", "-newkey", "rsa:2048", 
        "-keyout", f"{base_dir}/client.key", 
        "-out", f"{base_dir}/client.csr", 
        "-nodes", "-subj", "/CN=TestClient"
    ], stderr=subprocess.DEVNULL)
    
    # Sign client
    subprocess.check_call([
        "openssl", "x509", "-req", 
        "-in", f"{base_dir}/client.csr", 
        "-CA", f"{base_dir}/ca.crt", 
        "-CAkey", f"{base_dir}/ca.key", 
        "-out", f"{base_dir}/client.crt", 
        "-days", "1"
    ], stderr=subprocess.DEVNULL)

class TestMTLS(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, 'server.log')
        generate_certs(self.temp_dir)
        
        # Start server as subprocess
        env = os.environ.copy()
        env['CHELON_HOST'] = '127.0.0.1'
        env['CHELON_PORT'] = '15050'
        env['CHELON_SSL_CERT'] = f"{self.temp_dir}/server.crt"
        env['CHELON_SSL_KEY'] = f"{self.temp_dir}/server.key"
        env['CHELON_SSL_CA'] = f"{self.temp_dir}/ca.crt"
        env['CHELON_SSL_VERIFY_CLIENT'] = "true"
        env['PYTHONPATH'] = os.path.dirname(__file__) + os.pathsep + env.get('PYTHONPATH', '')
        
        server_path = os.path.join(os.path.dirname(__file__), '../server/chelon-service.py')
        
        self.server_process = subprocess.Popen(
            [sys.executable, server_path],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for server startup
        time.sleep(2)
        
        # Check if server started
        if self.server_process.poll() is not None:
            stdout, stderr = self.server_process.communicate()
            print(f"Server failed to start. Return code: {self.server_process.returncode}")
            print(f"STDOUT:\n{stdout.decode()}")
            print(f"STDERR:\n{stderr.decode()}")
            raise RuntimeError("Server failed to start")
        
    def tearDown(self):
        if self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
        
        # Print server output if tests failed (optional, but helpful)
        # For now, let's just cleanup
        shutil.rmtree(self.temp_dir)
        
    def test_https_connection_with_client_cert(self):
        url = "https://127.0.0.1:15050/api/v1/health"
        cert = (f"{self.temp_dir}/client.crt", f"{self.temp_dir}/client.key")
        ca = f"{self.temp_dir}/ca.crt"
        
        print("Testing valid mTLS connection...")
        response = requests.get(url, cert=cert, verify=ca)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'healthy')
        print("Success!")
        
    def test_https_connection_missing_cert(self):
        url = "https://127.0.0.1:15050/api/v1/health"
        ca = f"{self.temp_dir}/ca.crt"
        
        print("Testing missing client cert (should fail)...")
        with self.assertRaises(requests.exceptions.SSLError):
            requests.get(url, verify=ca)
        print("Caught expected SSL error!")

if __name__ == '__main__':
    unittest.main()
