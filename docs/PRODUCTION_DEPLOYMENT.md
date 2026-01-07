# Chelon Production Deployment Guide

## Overview

Chelon can run in two modes:
1. **Flask built-in server** (simple, works great for most cases)
2. **Gunicorn + Nginx** (optional, for high-traffic scenarios)

**For most deployments, the Flask built-in server is perfectly fine.**

---

## Option 1: Flask Built-in Server (Recommended)

This is what you're already using! It's simple and works well.

### Current Setup

Your systemd service already runs Flask:

```bash
# Check current setup
sudo systemctl status chelon
```

**File:** `/usr/lib/systemd/system/chelon.service`
```ini
[Service]
ExecStart=/usr/bin/python3 /usr/share/chelon/server/chelon-service.py
```

### When to Use Flask
- ✅ Small to medium deployments (1-10 build servers)
- ✅ Up to ~50 requests/minute
- ✅ Simple setup, no extra dependencies
- ✅ **This is what's running on gamera right now**

### Pros
- Simple - no extra software needed
- Easy to debug
- Works perfectly for typical build infrastructure

### Cons
- Single-threaded (handles one request at a time)
- Not optimized for high concurrency

---

## Option 2: Gunicorn (Optional, For High Traffic)

**What is Gunicorn?**
Gunicorn is a "production-grade" web server that can handle multiple requests simultaneously. Think of it as a more powerful version of Flask's built-in server.

### When to Use Gunicorn
- ⚠️ High traffic (100+ requests/minute)
- ⚠️ Many concurrent build servers (20+)
- ⚠️ Need multiple worker processes

**You probably don't need this unless you're scaling up significantly.**

### Setup (If Needed)

1. **Install Gunicorn**
   ```bash
   sudo pip3 install gunicorn
   ```

2. **Update systemd service**
   ```bash
   sudo vi /usr/lib/systemd/system/chelon.service
   ```
   
   Change `ExecStart` to:
   ```ini
   ExecStart=/usr/local/bin/gunicorn \
       --workers 4 \
       --bind 0.0.0.0:5050 \
       --chdir /usr/share/chelon/server \
       chelon-service:app
   ```

3. **Restart service**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart chelon
   ```

---

## SSL/HTTPS Configuration

Both Flask and Gunicorn support SSL directly - no Nginx needed!

### Current Setup (Flask with SSL)

Your current config in `/etc/chelon/chelon.conf`:
```bash
CHELON_SSL_CERT=/etc/chelon/certs/server.crt
CHELON_SSL_KEY=/etc/chelon/certs/server.key
CHELON_SSL_CA=/etc/chelon/certs/ca.crt
CHELON_SSL_VERIFY_CLIENT=true
```

This already provides:
- ✅ HTTPS encryption
- ✅ Client certificate authentication (mTLS)
- ✅ Secure communication

**You're already production-ready!**

---

## What About Nginx?

**Nginx is a reverse proxy** - it sits in front of your application and handles:
- Load balancing across multiple servers
- SSL termination
- Static file serving
- Advanced routing

### When to Use Nginx
- ⚠️ Multiple Chelon servers (high availability)
- ⚠️ Complex routing requirements
- ⚠️ Serving static files

**For a single Chelon server, you don't need Nginx.**

---

## Performance Comparison

| Setup | Requests/sec | Complexity | Use Case |
|-------|--------------|------------|----------|
| Flask (current) | 10-20 | Simple | Most deployments |
| Gunicorn | 50-100 | Medium | High traffic |
| Gunicorn + Nginx | 100-200 | Complex | Enterprise scale |

**Your typical build server makes 1-10 requests/minute, so Flask is perfect.**

---

## Monitoring Your Current Setup

### Check Service Status
```bash
sudo systemctl status chelon
```

### View Logs
```bash
# Real-time logs
sudo journalctl -u chelon -f

# Recent logs
sudo journalctl -u chelon -n 100
```

### Check Performance
```bash
# View audit logs to see request volume
sudo chelon-admin audit --limit 100

# Check if service is responding
curl -k https://localhost:5050/api/v1/health
```

---

## When to Upgrade

Consider upgrading to Gunicorn if you see:
- ❌ Slow response times (>1 second per request)
- ❌ Requests timing out
- ❌ High CPU usage on chelon process
- ❌ More than 50 requests/minute

**Until then, stick with Flask - it's simpler and works great.**

---

## High Availability (Optional)

If you need redundancy, run multiple Chelon servers:

1. **Deploy Chelon on 2-3 servers**
2. **Share the GPG keyring** (NFS or copy keys to each server)
3. **Use DNS round-robin** or a simple load balancer

But again, **most deployments don't need this**.

---

## Security Checklist

Your current setup already has:
- ✅ HTTPS/TLS encryption
- ✅ Client certificate authentication (mTLS)
- ✅ Token-based API auth
- ✅ Rate limiting
- ✅ Audit logging
- ✅ Secure file permissions

**You're already following best practices!**

---

## Troubleshooting

### Service Won't Start
```bash
# Check logs
sudo journalctl -u chelon -xe

# Test manually
sudo -u chelon python3 /usr/share/chelon/server/chelon-service.py
```

### Slow Performance
```bash
# Check request volume
sudo chelon-admin audit --limit 100 | wc -l

# If >50 requests/minute, consider Gunicorn
```

### Connection Refused
```bash
# Check if service is listening
sudo netstat -tlnp | grep 5050

# Check firewall
sudo firewall-cmd --list-all
```

---

## Summary

**Current Setup (Flask):**
- ✅ Simple and reliable
- ✅ Handles typical build server load
- ✅ Already has SSL/mTLS
- ✅ Production-ready as-is

**When to Upgrade:**
- Only if you see performance issues
- Only if you have 20+ concurrent build servers
- Only if you need high availability

**Bottom Line:** Your current Flask setup is perfect for production. Don't overcomplicate it unless you actually need the extra capacity.
