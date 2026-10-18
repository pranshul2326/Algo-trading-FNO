# Saidarshan on Amazon Lightsail

This deployment runs one Saidarshan process on one Ubuntu Lightsail instance for three team members. The browser-facing service is Caddy with HTTPS and individual HTTP Basic Auth accounts; FastAPI listens only on server loopback.

The product was renamed from Matheran to Saidarshan in the UI and documentation only. Every technical name below keeps `matheran`: the systemd unit, `/opt/matheran/*`, the Caddy include files, the SSH key name, the hostname and `MATHERAN_API_KEY`. Renaming them is a separate migration.

## Architecture

- AWS selected Region: `ap-southeast-2` (Sydney)
- Lightsail bundle: `micro_3_2` — 2 vCPU, 1 GiB RAM, 40 GB SSD
- Public URL: `https://matheran.54.252.125.60.sslip.io`
- Public proxy: Caddy on ports 80/443 with automatic HTTPS
- Application: one systemd-managed Uvicorn process on `127.0.0.1:8787`
- Authentication: individual Caddy users `team1`, `team2`, `team3`, plus the shared application API key
- Public read-only settings status: authenticated `GET /api/settings-view`, with server paths and credential previews sanitized
- Blocked remotely: `/api/settings`, settings mutation subroutes (including the per-workspace saves under `/api/settings/workspaces/`), `/docs*`, `/redoc*`, and `/openapi.json`
- Pages: `/` is the Sai Baba Live Darshan Portal landing page; the console is `/app` (`/app/<workspace>/<view>`, `/app/system`). `/charts`, `/chain`, `/combo` and old `/#trade`-style bookmarks keep working. Caddy proxies every path, so the Caddyfile needs no change
- Persistence: `/opt/matheran/app/data`, `cache`, `.env`, and `config.yaml`
- Initial mode: always forced to `paper`

## Cost boundary

The bundle is USD 7/month. Caddy, HTTPS certificates, and sslip.io DNS add no AWS resources. An attached Lightsail static IP has no additional charge. This setup intentionally creates no snapshots, extra disks, managed databases, load balancers, NAT gateways, Route 53 zones, or CDNs.

AWS Budgets alerts do not stop resources. Taxes, data transfer above the included allowance, detached static-IP charges, or unrelated resources can exceed USD 7. For project-level spending control, use AWS Settings. Do not detach and retain the static IP: keep it attached or release it.

## Team access

1. The administrator retrieves credentials once:

   ```bash
   ssh -i ~/.ssh/matheran-lightsail ubuntu@54.252.125.60 \
     'sudo cat /root/matheran-team-credentials.txt'
   ```

2. Give each member only their assigned `team1`, `team2`, or `team3` password through a secure channel.
3. Open `https://matheran.54.252.125.60.sslip.io` and enter that username/password. The address opens the landing page; **Enter Saidarshan** (or `/app`) opens the console.
4. Caddy authenticates the user and injects the server-side application API key; team members do not receive or enter `MATHERAN_API_KEY`.
5. After securely recording/distributing all passwords, remove the plaintext server copy:

   ```bash
   ssh -i ~/.ssh/matheran-lightsail ubuntu@54.252.125.60 \
     'sudo rm -f /root/matheran-team-credentials.txt'
   ```

The password hashes remain in `/etc/caddy/matheran-users`. Rotate an account by creating a new Caddy hash and replacing only that user's line.

## Paper and live operation

The public proxy denies all settings and credential-management routes. To administer settings, create an owner-only SSH tunnel:

```bash
ssh -i ~/.ssh/matheran-lightsail -N \
  -L 8878:127.0.0.1:8787 ubuntu@54.252.125.60
```

Then open `http://127.0.0.1:8878/app/system` for mode, brokers and credentials, or a workspace's Setup and Strategy views for its own settings. Only switch to live after confirming the Dhan static-IP allowlist, broker credentials, stop-order behavior, persistence, and reconciliation after restart.

The application has one server-side API key and no per-user application roles. Caddy injects that key after individual login. In live mode, every authenticated team member can exercise owner-level trade controls. Keep the shared deployment in paper mode unless all three people are trusted to control the same broker account.

## Operations

```bash
sudo systemctl status matheran caddy --no-pager
sudo journalctl -u matheran -f
sudo journalctl -u caddy -f
sudo systemctl restart matheran
curl http://127.0.0.1:8787/health
```

Do not run multiple Uvicorn workers, processes, or Lightsail instances against the same broker account. Engine state and file persistence assume one writer.

## Backup and restore

No paid automatic snapshots are enabled to respect the USD 7/month resource target. Manually copy `data/` and reviewed `config.yaml` to secure storage. Treat `.env` as a secret and `cache/` as rebuildable. Test restore and reconciliation in paper mode.

## Removal

Before deleting the instance, stop trading and reconcile broker positions and orders. Download required `data/`, then delete the instance and release the static IP. A detached static IP can incur charges.
