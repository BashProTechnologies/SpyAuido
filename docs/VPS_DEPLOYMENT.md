# VPS Deployment Guide (Ubuntu 24.04 LTS)

Follow these step-by-step instructions to deploy the Baby Monitor Central Relay Server on an Ubuntu 24.04 LTS VPS with TLS/WSS encryption.

---

## 1. VPS Server Provisioning
Create an Ubuntu 24.04 LTS server instance on Hetzner, DigitalOcean, Linode, or AWS with at least 1 vCPU and 1 GB RAM.

## 2. SSH Connection & System Update
Connect via SSH:
```bash
ssh root@<YOUR_VPS_IP>
```
Update system packages:
```bash
sudo apt update && sudo apt upgrade -y
```

## 3. Install Docker & Docker Compose
```bash
sudo apt install -y curl git ufw
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo systemctl enable --now docker
```

## 4. Domain & DNS Configuration
In your DNS provider (e.g. Cloudflare / Namecheap), create an `A` record pointing your domain/subdomain to your VPS IP:
```
baby.example.com  -->  <YOUR_VPS_IP>
```
*Note for Cloudflare users:* Disable Cloudflare Proxy (Set to **DNS Only - Gray Cloud**) for WebSocket & raw UDP streaming compatibility if using custom ports, or enable WebSockets in Cloudflare dashboard settings.

## 5. Security & Firewall Configuration (UFW)
Only open necessary ports:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (Let's Encrypt renewal)
sudo ufw allow 443/tcp   # HTTPS / WSS
sudo ufw enable
```

## 6. Install Let's Encrypt TLS Certificate (Certbot)
```bash
sudo apt install -y certbot nginx
sudo systemctl stop nginx
sudo certbot certonly --standalone -d baby.example.com
```

## 7. Deploy Server with Docker Compose
Clone or upload the project code to `/opt/baby-monitor`:
```bash
mkdir -p /opt/baby-monitor
cd /opt/baby-monitor
# Upload server code
```
Create production environment variables file `.env` in `server/`:
```bash
cat <<EOF > server/.env
DEBUG=False
HOST=0.0.0.0
PORT=8000
SECRET_KEY=$(openssl rand -hex 32)
BABY_DEVICE_ID=baby_room_pc_01
BABY_DEVICE_TOKEN=$(openssl rand -hex 16)
PARENT_DEVICE_ID=parent_room_pc_01
PARENT_DEVICE_TOKEN=$(openssl rand -hex 16)
EOF
```

Start Docker container:
```bash
cd /opt/baby-monitor/server
docker compose up -d --build
```

## 8. Configure Nginx Reverse Proxy & Restart
Copy `deployment/nginx/nginx.conf` to `/etc/nginx/sites-available/baby.example.com`:
```bash
sudo cp /opt/baby-monitor/deployment/nginx/nginx.conf /etc/nginx/sites-available/baby.example.com
sudo ln -s /etc/nginx/sites-available/baby.example.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 9. Verification & Troubleshooting
Check server health:
```bash
curl https://baby.example.com/health
```
View container logs:
```bash
docker compose logs -f
```
Restart server:
```bash
docker compose restart
```
