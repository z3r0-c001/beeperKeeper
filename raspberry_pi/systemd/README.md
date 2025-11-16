# BeeperKeeper Systemd Service Configuration

**Purpose:** Fixed systemd service files and deployment tools for BeeperKeeper auto-recovery on reboot

**Date Created:** November 5, 2025
**Issue:** Ordering cycle preventing automatic service startup
**Status:** Ready for deployment

---

## Quick Start

### Deploy the Fix (Automated)
```bash
cd /home/dev_user/codeOne/beeperKeeper/v2_0/raspberry_pi/systemd/
./deploy_fixed_services.sh
```

The script will backup, deploy, and verify the fix. Follow the on-screen instructions.

### After Deployment - Test Reboot
```bash
# When ready to test auto-recovery
ssh pi_user@10.10.10.28 "sudo reboot"

# Wait 3 minutes, then verify
ssh pi_user@10.10.10.28 "systemctl is-active mqtt-publisher mediamtx flask-app"
# Expected: active / active / active
```

---

## Directory Contents

### Service Configuration Files
- **mqtt-publisher.service** - MQTT sensor data publisher (fixed)
- **mediamtx.service** - Camera streaming server (fixed)
- **flask-app.service** - Web interface (fixed)

**Fix Applied:** `network.target` → `network-online.target` to break ordering cycle

### Deployment Tools
- **deploy_fixed_services.sh** - Automated deployment script (recommended)
- **rollback_services.sh** - Automated rollback script (emergency)

### Documentation
- **README.md** - This file (overview)
- **FIX_SUMMARY.md** - Executive summary and complete documentation
- **DEPLOYMENT_PROCEDURE.md** - Detailed manual deployment steps
- **REBOOT_TEST_CARD.md** - Quick reference for reboot testing

---

## What Was Fixed

### The Problem
**Symptom:** Services failed to start automatically on reboot, requiring manual `systemctl start` commands.

**Root Cause:** Systemd ordering cycle caused by circular dependency:
```
multi-user.target → services → network.target → (implicit) multi-user.target
```

**Impact:** 18-19 minute downtime on every reboot.

### The Solution
**Change:** All services now use `network-online.target` instead of `network.target`

**Why This Works:**
- `network.target` = network subsystem initialized (early in boot)
- `network-online.target` = actual network connectivity (after multi-user.target)
- Breaks circular dependency chain
- Services only start when network is actually available

**Impact:** Zero downtime during deployment, automatic recovery on reboot after deployment.

---

## Deployment Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Read Documentation                                       │
│    - FIX_SUMMARY.md (recommended starting point)            │
│    - DEPLOYMENT_PROCEDURE.md (detailed steps)               │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ 2. Deploy Fix                                               │
│    OPTION A: ./deploy_fixed_services.sh (automated)         │
│    OPTION B: Follow DEPLOYMENT_PROCEDURE.md (manual)        │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ 3. Verify Deployment                                        │
│    - Script shows all green checkmarks                      │
│    - No ordering cycles detected                            │
│    - Services still running                                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ 4. Test Reboot (when ready)                                 │
│    - Use REBOOT_TEST_CARD.md as reference                   │
│    - ssh pi_user@10.10.10.28 "sudo reboot"                   │
│    - Wait 3 minutes                                         │
└─────────────────────┬───────────────────────────────────────┘
                      │
         ┌────────────▼────────────┐
         │ Services auto-started?  │
         └────┬─────────────┬──────┘
              │ YES         │ NO
    ┌─────────▼───────┐   ┌▼────────────────────┐
    │ ✅ SUCCESS      │   │ ❌ FAILURE          │
    │ - Verify tests  │   │ - Collect logs      │
    │ - Monitor 24hrs │   │ - Run rollback      │
    │ - Update docs   │   │ - Investigate       │
    └─────────────────┘   └─────────────────────┘
```

---

## Files Explained

### mqtt-publisher.service
**Purpose:** Publishes sensor data from BME680 to MQTT broker
**Dependencies:** Requires network connectivity (MQTT broker at 10.10.10.7)
**Fix:** Changed to wait for `network-online.target`

### mediamtx.service
**Purpose:** RTSP/HLS/WebRTC streaming server for cameras
**Dependencies:** Requires network connectivity (clients connect remotely)
**Fix:** Changed to wait for `network-online.target`

### flask-app.service
**Purpose:** Web interface for camera streams and system monitoring
**Dependencies:** Requires network + mediamtx.service
**Fix:** Changed to wait for `network-online.target`, still depends on mediamtx

---

## Verification Commands

### Before Deployment
```bash
# Check current service status
ssh pi_user@10.10.10.28 "systemctl status mqtt-publisher mediamtx flask-app"

# Check for existing ordering cycles
ssh pi_user@10.10.10.28 "journalctl | tail -1000 | grep 'ordering cycle'"
```

### After Deployment (Before Reboot)
```bash
# Verify service files syntax
ssh pi_user@10.10.10.28 "systemd-analyze verify mqtt-publisher.service"
ssh pi_user@10.10.10.28 "systemd-analyze verify mediamtx.service"
ssh pi_user@10.10.10.28 "systemd-analyze verify flask-app.service"

# Check for ordering cycles
ssh pi_user@10.10.10.28 "systemd-analyze critical-chain mqtt-publisher.service" | grep -i cycle
# Expected: (no output)
```

### After Reboot Test
```bash
# Quick status check
ssh pi_user@10.10.10.28 "systemctl is-active mqtt-publisher mediamtx flask-app"
# Expected: active / active / active

# Check for ordering cycle errors
ssh pi_user@10.10.10.28 "journalctl -b | grep 'ordering cycle'"
# Expected: (no output)

# Verify web interface
curl -I http://10.10.10.28:8888
# Expected: HTTP 200
```

---

## Rollback Instructions

**If reboot test fails:**

### Option 1: Automated Rollback
```bash
cd /home/dev_user/codeOne/beeperKeeper/v2_0/raspberry_pi/systemd/
./rollback_services.sh
```

### Option 2: Manual Rollback
```bash
# Restore backup files
ssh pi_user@10.10.10.28 "sudo cp -p /etc/systemd/system/*.backup-2025-11-05 /etc/systemd/system/"
ssh pi_user@10.10.10.28 "sudo systemctl daemon-reload"

# Restart services
ssh pi_user@10.10.10.28 "sudo systemctl start mediamtx flask-app mqtt-publisher"
```

**Note:** Backup files are created automatically during deployment at:
- `/etc/systemd/system/mqtt-publisher.service.backup-2025-11-05`
- `/etc/systemd/system/mediamtx.service.backup-2025-11-05`
- `/etc/systemd/system/flask-app.service.backup-2025-11-05`

---

## Risk Assessment

**Deployment Risk:** ⚠️ LOW
- Services remain running during deployment
- Changes only affect boot behavior
- Backups created automatically
- Full rollback capability

**Reboot Risk:** ⚠️ LOW-MEDIUM
- First reboot after fix may reveal unexpected issues
- System fully recoverable via manual service start
- Rollback procedure tested and documented

**Mitigation:**
- Comprehensive pre-deployment verification
- Automated deployment script with checks
- Detailed reboot test procedure
- Emergency rollback script ready

---

## Success Criteria

**Deployment Success:**
- ✅ All verification steps pass
- ✅ No ordering cycles detected
- ✅ Services remain running
- ✅ Backups created

**Reboot Test Success:**
- ✅ All services auto-start (no manual intervention)
- ✅ No ordering cycle errors in logs
- ✅ Services start within 1-2 minutes of boot
- ✅ Web interface accessible
- ✅ Camera streams working
- ✅ Sensor data flowing to Grafana

---

## Troubleshooting

### Deployment Script Fails
**Symptom:** Script shows red errors during deployment

**Actions:**
1. Read error message carefully
2. Check SSH connectivity: `ssh pi_user@10.10.10.28 "echo test"`
3. Verify local service files exist
4. Re-run with verbose output (edit script to add `set -x`)

### Services Don't Start After Reboot
**Symptom:** `systemctl is-active` shows `inactive` or `failed`

**Actions:**
1. Manually start services: `sudo systemctl start mediamtx flask-app mqtt-publisher`
2. Check logs: `journalctl -b -u mqtt-publisher -u mediamtx -u flask-app`
3. Look for ordering cycles: `journalctl -b | grep 'ordering cycle'`
4. Run rollback script if needed

### Ordering Cycles Still Present
**Symptom:** `journalctl -b | grep 'ordering cycle'` shows matches after deployment

**Actions:**
1. Verify service files were updated: `systemctl cat mqtt-publisher.service | grep network-online`
2. Check systemd daemon was reloaded: `systemctl daemon-reload`
3. Re-run deployment script
4. Contact support with full logs

---

## Additional Resources

- **Original Analysis:** `/home/dev_user/codeOne/beeperKeeper/v2_0/SERVICE_STARTUP_FAILURE_ANALYSIS_2025-11-05.md`
- **Systemd Documentation:** `man systemd.special(7)`, `man systemd.service(5)`
- **Network Targets:** https://systemd.io/NETWORK_ONLINE/
- **Project CLAUDE.md:** `/home/dev_user/codeOne/beeperKeeper/v2_0/CLAUDE.md`

---

## Questions?

**Common Questions Answered in FIX_SUMMARY.md:**
- Why not use `DefaultDependencies=no`?
- Why keep `WantedBy=multi-user.target`?
- Will this affect boot time?
- Can I revert if something goes wrong?
- Do I need to stop services during deployment?

**Read:** `FIX_SUMMARY.md` section "Questions & Answers"

---

**Status:** ✅ Ready for deployment
**Last Updated:** November 5, 2025
**Author:** Claude (embedded-systems-architect)
**System:** Raspberry Pi 3B+ @ 10.10.10.28 (motionTwo)
