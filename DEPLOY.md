# Deploy OI Dashboard to Ubuntu (production)

Deploy the Docker image from GitHub Container Registry to an Ubuntu server with Docker, a systemd service, and optional Nginx reverse proxy.

## Prerequisites

- Ubuntu 22.04 or 24.04 (or similar)
- SSH access to the server
- PostgreSQL reachable from the server (same host or remote)
- (Optional) Domain and SSL for HTTPS

---

## 1. Install Docker on the server

```bash
# Update and install Docker
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a644 /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
sudo usermod -aG docker "$USER"
# Log out and back in (or newgrp docker) for group to apply
```

---

## 2. Create app directory and env file

```bash
sudo mkdir -p /opt/oi-dashboard
sudo chown "$USER:$USER" /opt/oi-dashboard
cd /opt/oi-dashboard
```

Create `/opt/oi-dashboard/.env` with your production values:

```env
OI_TRACKER_DB_TYPE=postgres
OI_TRACKER_DB_HOST=localhost
OI_TRACKER_DB_PORT=5432
OI_TRACKER_DB_NAME=oi_db_live
OI_TRACKER_DB_USER=your_db_user
OI_TRACKER_DB_PASSWORD=your_db_password

FLASK_HOST=0.0.0.0
FLASK_PORT=5055
```

Optional (if trade logs live elsewhere):

```env
OI_TRACKER_TRADE_LOG_DIR=/path/to/trade_logs
```

Secure the env file:

```bash
chmod 600 /opt/oi-dashboard/.env
```

---

## 3. Log in to GHCR and pull the image

If the image is **private**, log in once (use a [PAT](https://github.com/settings/tokens) with `read:packages`):

```bash
echo YOUR_GITHUB_TOKEN | sudo docker login ghcr.io -u kpalastro --password-stdin
```

Pull the image:

```bash
sudo docker pull ghcr.io/kpalastro/oi-dashboard:latest
```

---

## 4. Run the container (manual test)

```bash
sudo docker run -d \
  --name oi-dashboard \
  --restart unless-stopped \
  -p 5055:5055 \
  --env-file /opt/oi-dashboard/.env \
  ghcr.io/kpalastro/oi-dashboard:latest
```

Check logs: `sudo docker logs -f oi-dashboard`  
Stop: `sudo docker stop oi-dashboard && sudo docker rm oi-dashboard`

---

## 5. Production: systemd service (recommended)

This keeps the app running, restarts on failure, and starts on boot.

Create `/etc/systemd/system/oi-dashboard.service`:

```ini
[Unit]
Description=OI Dashboard (Docker)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker pull ghcr.io/kpalastro/oi-dashboard:latest
ExecStart=/usr/bin/docker run --rm --name oi-dashboard -p 5055:5055 --env-file /opt/oi-dashboard/.env ghcr.io/kpalastro/oi-dashboard:latest
ExecStop=/usr/bin/docker stop oi-dashboard
TimeoutStartSec=300
TimeoutStopSec=30
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable oi-dashboard
sudo systemctl start oi-dashboard
sudo systemctl status oi-dashboard
```

Useful commands:

- **Logs:** `sudo journalctl -u oi-dashboard -f`
- **Restart after new image:** `sudo systemctl restart oi-dashboard` (pulls latest on next start if you add `ExecStartPre=-/usr/bin/docker pull ...` as above)
- **Stop:** `sudo systemctl stop oi-dashboard`

---

## 6. Optional: Nginx reverse proxy (HTTPS)

If you want to serve the app behind Nginx with HTTPS (e.g. `https://dashboard.example.com`):

1. Install Nginx and Certbot:

   ```bash
   sudo apt install -y nginx certbot python3-certbot-nginx
   ```

2. Create a server block, e.g. `/etc/nginx/sites-available/oi-dashboard`:

   ```nginx
   server {
       listen 80;
       server_name dashboard.example.com;
       location / {
           proxy_pass http://127.0.0.1:5055;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

3. Enable the site and get a certificate:

   ```bash
   sudo ln -s /etc/nginx/sites-available/oi-dashboard /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d dashboard.example.com
   ```

4. The app still listens on `127.0.0.1:5055` (or bind Nginx to the same host). If the container binds to `0.0.0.0:5055`, use `proxy_pass http://127.0.0.1:5055;` so only Nginx talks to it.

---

## 7. Updating to a new image

After CI pushes a new image to GHCR:

```bash
sudo docker pull ghcr.io/kpalastro/oi-dashboard:latest
sudo systemctl restart oi-dashboard
```

If you use the systemd unit with `ExecStartPre=-/usr/bin/docker pull ...`, a simple `sudo systemctl restart oi-dashboard` will pull and run the latest image.

---

## 8. CD: Auto-deploy to server on push

The GitHub Actions workflow can SSH into your server after each push to `main` and run `docker pull` + restart the container.

**Prerequisites on the server:**

- Docker installed; user used by GitHub can run `docker` (e.g. in `docker` group).
- **Project folder** `/home/kuldeep/Projects/OI_Dashboard` exists and contains `.env` with correct DB and Flask settings. (Path is set in workflow env `APP_PATH`; change it in `.github/workflows/ci.yml` if needed.)
- Container network `n8n_default` exists (or change the workflow to your network name).
- SSH access: key-based auth for the deploy user.

**GitHub repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Server hostname or IP (e.g. `192.168.1.10` or `myserver.example.com`) |
| `DEPLOY_USER` | SSH user (e.g. `ubuntu` or `deploy`) |
| `DEPLOY_SSH_KEY` | Private key content for SSH (the full key, including `-----BEGIN ... -----`) |

**What the CD job does:**

1. Runs only on **push to `main`**, after the image is built and pushed to GHCR.
2. SSHs into the server and runs:
   - `docker pull ghcr.io/<owner>/oi-dashboard:latest`
   - `docker stop oi-dashboard` (if running)
   - `docker rm oi-dashboard` (if exists)
   - `docker run -d --name oi-dashboard ... --network n8n_default --env-file "$APP_PATH/.env" ...` (where `APP_PATH` is `/home/kuldeep/Projects/OI_Dashboard` by default)

**Customise:** Edit `.github/workflows/ci.yml` job `deploy-server` to change `APP_PATH`, the Docker network, or run options. If you don’t set the secrets, the deploy-server job will fail but the workflow is marked `continue-on-error: true`, so the rest of CI still passes.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Install Docker on Ubuntu |
| 2 | Create `/opt/oi-dashboard` and `.env` with DB and Flask settings |
| 3 | Log in to GHCR (if private) and pull `ghcr.io/kpalastro/oi-dashboard:latest` |
| 4 | Run container manually to test |
| 5 | Install systemd unit for production (restart on failure, start on boot) |
| 6 | (Optional) Nginx + Certbot for HTTPS |
| 7 | Update: pull image and restart the service |
| 8 | (Optional) Add GitHub secrets for CD: auto-deploy to server on push to `main` |
