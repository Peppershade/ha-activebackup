# Synology Active Backup for Business — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.4%2B-blue.svg)](https://www.home-assistant.io/)

Monitor your [Synology Active Backup for Business](https://www.synology.com/en-us/dsm/feature/active_backup_business) tasks directly from Home Assistant. Track backup status, last result, live progress, and scheduled run times — one set of sensors per backup task.

---

## Features

- **Per-task sensors** for every Active Backup task on your NAS
- **Live progress** during an active backup (polls every 3 seconds while running, every 60 seconds when idle)
- **Last result** — Success, Warning, Error, or Unknown
- **Timestamps** for last completed backup and next scheduled backup
- **Transferred size** and **duration** of the last backup run
- **Two-factor authentication** support (TOTP + device token remembered after first login)
- **Re-authentication flow** if credentials expire
- Dutch and English UI translations

---

## Sensors

Each backup task creates the following sensors:

| Sensor | Description |
|---|---|
| **Status** | `Running` or `Idle` |
| **Last Result** | `Success`, `Warning`, `Error`, or `Unknown` |
| **Last Backup** | Timestamp of the last completed backup |
| **Next Backup** | Timestamp of the next scheduled backup |
| **Transferred Size** | Data transferred during the last backup |
| **Duration** | How long the last backup took |
| **Progress** | Live percentage during a running backup (0% when idle) |

---

## Requirements

- Synology NAS running DSM 7 with Active Backup for Business installed and licensed
- A DSM user account with access to Active Backup for Business
- Home Assistant 2024.4 or newer

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** and click the three-dot menu in the top right.
3. Select **Custom repositories**.
4. Add `https://github.com/Peppershade/ha-activebackup` as an **Integration**.
5. Search for **Synology Active Backup for Business** and install it.
6. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/activebackup` folder into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Synology Active Backup for Business**.
3. Enter your NAS details:
   - **Host** — hostname or IP address of your Synology NAS
   - **Port** — `5001` for HTTPS (default), `5000` for HTTP
   - **Username / Password** — DSM account credentials
   - **Use HTTPS** — recommended; disable only for plain HTTP setups
   - **Verify SSL certificate** — disable if you use a self-signed certificate
4. Click **Submit**.

### Two-factor authentication

If your DSM account has 2FA enabled, you will be prompted to enter the one-time password from your authenticator app. After a successful login the device token is stored, so you will not be asked again unless you re-authenticate.

---

## Troubleshooting

**No entities appear after setup**
Make sure the DSM user has permission to access Active Backup for Business. Log in to DSM and confirm you can open the Active Backup for Business package.

**Entities become unavailable after a while**
This is usually a session expiry. The integration automatically re-authenticates on the next poll. If it keeps happening, check that the DSM account password has not changed and that no IP-based session restrictions are in place.

**SSL errors**
If your NAS uses a self-signed certificate, disable **Verify SSL certificate** during setup.

---

## License

MIT
