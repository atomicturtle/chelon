# Chelon Production Deployment Guide

## Overview

This guide covers deploying Chelon in a production environment using Gunicorn as the WSGI server and Nginx as a reverse proxy.

---

## Architecture

```
[Build Servers] 
    ↓ HTTPS + mTLS
[Nginx :443] 
    ↓ HTTP (localhost)
[Gunicorn :5050]
    ↓
[Chelon Flask App]
    ↓
[GPG Keyring]
```

---

## Prerequisites

- RHEL/Rocky/Fedora Linux
- Python 3.9+
- Nginx
- GPG keys imported
- SSL/TLS certificates

---

## Installation

### 1. Install Packages

```bash
# Install Chelon
sudo dnf install chelon-server-1.0.0-2.fc43.noarch.rpm

# Install Gunicorn
sudo pip3 install gunicorn
```

### 2. Configure Keys

```bash
# Import GPG keys as chelon user
sudo -u chelon gpg --homedir /var/lib/chelon/.gnupg --import /path/to/keys.asc

# Configure keys
sudo chelon-admin keys add legacy 4520AFA9 --description "Legacy signing key"
sudo chelon-admin keys add modern CB2C73F04F3BE076 --description "Modern signing key"
sudo chelon-admin keys set-default modern
```

### 3. Generate API Tokens

```bash
# Create token for build servers
sudo chelon-admin generate-token build-runner-01 \
  --permissions sign:rpm,sign:repodata \
  --rate-limit 100
```

---

## Gunicorn Configuration

### Create Gunicorn Config

**File:** `/etc/chelon/gunicorn.conf.py`

```python
import multiprocessing

# Server socket
bind = "127.0.0.1:5050"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2

# Logging
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "chelon"

# Server mechanics
daemon = False
pidfile = "/var/run/chelon/gunicorn.pid"
umask = 0o007
user = "chelon"
group = "chelon"
tmp_upload_dir = None

# SSL (if not using Nginx)
# keyfile = "/etc/chelon/certs/server.key"
# certfile = "/etc/chelon/certs/server.crt"
# ca_certs = "/etc/chelon/certs/ca.crt"
# cert_reqs = 2  # ssl.CERT_REQUIRED
```

### Create Systemd Service

**File:** `/etc/systemd/system/chelon-gunicorn.service`

```ini
[Unit]
Description=Chelon Gunicorn Service
After=network.target

[Service]
Type=notify
User=chelon
Group=chelon
RuntimeDirectory=chelon
WorkingDirectory=/usr/share/chelon/server

Environment="PATH=/usr/bin:/usr/local/bin"
Environment="PYTHONPATH=/usr/share/chelon/server"

ExecStart=/usr/local/bin/gunicorn \
    --config /etc/chelon/gunicorn.conf.py \
    chelon-service:app

ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable chelon-gunicorn
sudo systemctl start chelon-gunicorn
sudo systemctl status chelon-gunicorn
```

---

## Nginx Configuration

### Create Nginx Config

**File:** `/etc/nginx/conf.d/chelon.conf`

```nginx
upstream chelon_backend {
    server 127.0.0.1:5050 fail_timeout=0;
}

server {
    listen 443 ssl http2;
    server_name chelon.example.com;

    # SSL Configuration
    ssl_certificate /etc/chelon/certs/server.crt;
    ssl_certificate_key /etc/chelon/certs/server.key;
    ssl_client_certificate /etc/chelon/certs/ca.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;

    # SSL Security
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Logging
    access_log /var/log/nginx/chelon-access.log;
    error_log /var/log/nginx/chelon-error.log;

    # Proxy to Gunicorn
    location / {
        proxy_pass http://chelon_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-SSL-Client-Cert $ssl_client_cert;
        proxy_set_header X-SSL-Client-DN $ssl_client_s_dn;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        
        # Buffering
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Health check endpoint (no client cert required)
    location /api/v1/health {
        ssl_verify_client optional;
        proxy_pass http://chelon_backend;
    }
}
```

### Enable and Test

```bash
# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx

# Check status
sudo systemctl status nginx
```

---

## Monitoring

### Systemd Journal

```bash
# View Chelon logs
sudo journalctl -u chelon-gunicorn -f

# View audit logs
sudo journalctl -u chelon-gunicorn | grep AUDIT_ENTRY
```

### Nginx Logs

```bash
# Access log
sudo tail -f /var/log/nginx/chelon-access.log

# Error log
sudo tail -f /var/log/nginx/chelon-error.log
```

### Health Checks

```bash
# Internal health check
curl http://localhost:5050/api/v1/health

# External health check (with client cert)
curl --cert /path/to/client.crt \
     --key /path/to/client.key \
     --cacert /path/to/ca.crt \
     https://chelon.example.com/api/v1/health
```

---

## Performance Tuning

### Gunicorn Workers

```python
# Rule of thumb: (2 * CPU cores) + 1
workers = multiprocessing.cpu_count() * 2 + 1

# For CPU-bound tasks, use fewer workers
# For I/O-bound tasks, use more workers
```

### Nginx Tuning

```nginx
# Increase worker connections
events {
    worker_connections 4096;
}

# Enable keepalive to backend
upstream chelon_backend {
    server 127.0.0.1:5050;
    keepalive 32;
}
```

---

## High Availability

### Load Balancer Setup

```nginx
upstream chelon_cluster {
    least_conn;
    server chelon1.example.com:443 max_fails=3 fail_timeout=30s;
    server chelon2.example.com:443 max_fails=3 fail_timeout=30s;
    server chelon3.example.com:443 backup;
}

server {
    listen 443 ssl http2;
    server_name chelon-lb.example.com;
    
    location / {
        proxy_pass https://chelon_cluster;
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }
}
```

### Shared Storage

For HA deployments, share these directories:
- `/var/lib/chelon/tokens.json` - Token database
- `/var/lib/chelon/keys.json` - Key configuration
- `/var/lib/chelon/.gnupg` - GPG keyring

Options:
- NFS mount
- Distributed filesystem (GlusterFS, Ceph)
- Database backend (future enhancement)

---

## Security Checklist

- [ ] SSL/TLS certificates properly configured
- [ ] Client certificate verification enabled
- [ ] Config file permissions: `chmod 600 /etc/chelon/chelon.conf`
- [ ] Config file ownership: `chown root:chelon /etc/chelon/chelon.conf`
- [ ] Firewall rules: Only allow port 443 from build servers
- [ ] SELinux/AppArmor policies configured
- [ ] Regular security updates applied
- [ ] Audit logs monitored
- [ ] Rate limiting configured appropriately

---

## Troubleshooting

### Gunicorn Won't Start

```bash
# Check logs
sudo journalctl -u chelon-gunicorn -n 50

# Test manually
sudo -u chelon gunicorn --config /etc/chelon/gunicorn.conf.py chelon-service:app

# Check permissions
ls -la /var/lib/chelon/
```

### Nginx 502 Bad Gateway

```bash
# Check if Gunicorn is running
sudo systemctl status chelon-gunicorn

# Check Gunicorn is listening
sudo netstat -tlnp | grep 5050

# Check Nginx error log
sudo tail -f /var/log/nginx/chelon-error.log
```

### Client Certificate Errors

```bash
# Verify client cert
openssl x509 -in client.crt -text -noout

# Test SSL connection
openssl s_client -connect chelon.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt
```

---

## Backup and Recovery

### Backup

```bash
#!/bin/bash
# Backup script
BACKUP_DIR="/backup/chelon/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup configuration and data
cp -r /etc/chelon "$BACKUP_DIR/"
cp -r /var/lib/chelon "$BACKUP_DIR/"

# Create tarball
tar czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"
```

### Recovery

```bash
# Stop service
sudo systemctl stop chelon-gunicorn

# Restore data
sudo tar xzf /backup/chelon/20260107.tar.gz -C /

# Fix permissions
sudo chown -R chelon:chelon /var/lib/chelon
sudo chmod 600 /etc/chelon/chelon.conf

# Start service
sudo systemctl start chelon-gunicorn
```

---

## Maintenance

### Rotating Logs

Nginx logs rotate automatically via logrotate.

For application logs (journald):
```bash
# Configure journal retention
sudo vi /etc/systemd/journald.conf
# Set: SystemMaxUse=1G

# Restart journald
sudo systemctl restart systemd-journald
```

### Updating Chelon

```bash
# Stop service
sudo systemctl stop chelon-gunicorn

# Update RPM
sudo rpm -Uvh chelon-server-1.0.0-3.fc43.noarch.rpm

# Restart service
sudo systemctl start chelon-gunicorn

# Verify
curl http://localhost:5050/api/v1/health
```

---

## Performance Benchmarks

Expected performance (4-core server):
- **Throughput:** 100-200 requests/second
- **Latency:** 50-100ms per signing operation
- **Concurrent connections:** 1000+

Bottlenecks:
- GPG signing operations (CPU-bound)
- Disk I/O for GPG keyring access

---

## Support

For issues:
- Check logs: `journalctl -u chelon-gunicorn`
- Review audit trail: `chelon-admin audit`
- Contact: support@atomicorp.com
