# BeeperKeeper InfluxDB Backup & Restore Guide

## Overview

Automated system for backing up sensor data monthly and restoring it for analysis.

## System Configuration

- **Retention**: Main `sensors` bucket keeps 1 year of data
- **Backup Schedule**: Monthly on 1st at 2:00 AM (backs up data from 11 months ago)
- **Storage Location**: `/home/YOUR_USERNAME/beeperKeeper/backups/influxdb/YYYY/MM/`
- **Compression**: tar.gz format
- **Logs**: `/home/YOUR_USERNAME/beeperKeeper/backups/influx_backup.log`

## Directory Structure

```
~/beeperKeeper/
├── backups/
│   ├── influxdb/
│   │   ├── 2024/
│   │   │   ├── 11/
│   │   │   │   └── sensors_2024-11.tar.gz
│   │   │   ├── 12/
│   │   │   │   └── sensors_2024-12.tar.gz
│   │   ├── 2025/
│   │   │   ├── 01/
│   │   │   │   └── sensors_2025-01.tar.gz
│   ├── influx_backup.log
│   └── influx_restore.log
└── scripts/
    ├── influx_backup.sh
    └── influx_restore.sh
```

## Manual Backup

To manually trigger a backup (backs up data from 11 months ago):

```bash
ssh YOUR_USERNAME@YOUR_DOCKER_HOST_IP
cd ~/beeperKeeper/scripts
./influx_backup.sh
```

## Restoring Data for Analysis

To restore archived data to analyze in Grafana:

```bash
ssh YOUR_USERNAME@YOUR_DOCKER_HOST_IP
cd ~/beeperKeeper/scripts

# Restore November 2024 data
./influx_restore.sh 2024 11
```

This will:
1. Extract the compressed backup
2. Create temporary bucket: `sensors_archive_2024_11`
3. Restore data to this bucket
4. Provide instructions for viewing in Grafana

## Viewing Restored Data in Grafana

1. Open Grafana: http://YOUR_DOCKER_HOST_IP:3000
2. Go to **Connections → Data Sources → InfluxDB_Beeper**
3. Change **Default Bucket** from `sensors` to `sensors_archive_2024_11`
4. Save & Test
5. View your dashboards - they now show archived data!
6. **Remember to change bucket back to `sensors`** when done

## Deleting Temporary Buckets

After analyzing archived data, clean up the temporary bucket:

```bash
ssh YOUR_USERNAME@YOUR_DOCKER_HOST_IP
sudo docker exec beeper_influxdb influx bucket delete \
  --name sensors_archive_2024_11 \
  --org beeperKeeper
```

Or list all buckets to see what exists:

```bash
sudo docker exec beeper_influxdb influx bucket list
```

## Multi-Year Analysis

To compare data across multiple months:

1. Restore multiple months to separate buckets:
   ```bash
   ./influx_restore.sh 2024 01
   ./influx_restore.sh 2024 02
   ./influx_restore.sh 2024 03
   ```

2. Create custom Grafana dashboard with multiple queries pointing to different buckets

3. Use Flux to query across buckets:
   ```flux
   union(tables: [
     from(bucket: "sensors_archive_2024_01"),
     from(bucket: "sensors_archive_2024_02"),
     from(bucket: "sensors_archive_2024_03")
   ])
   |> range(start: 2024-01-01T00:00:00Z, stop: 2024-04-01T00:00:00Z)
   |> filter(fn: (r) => r["topic"] == "beeper/sensors/bme680/all")
   ```

## Monitoring Backups

Check backup logs:
```bash
ssh YOUR_USERNAME@YOUR_DOCKER_HOST_IP
tail -100 ~/beeperKeeper/backups/influx_backup.log
```

List all backups:
```bash
find ~/beeperKeeper/backups/influxdb -name "*.tar.gz" -exec ls -lh {} \;
```

## Cron Schedule

Backups run automatically via cron:
```
0 2 1 * * ~/beeperKeeper/scripts/influx_backup.sh
```

This means: Every month on the 1st day at 2:00 AM

## Troubleshooting

**Backup fails:**
- Check logs: `tail -50 ~/beeperKeeper/backups/influx_backup.log`
- Verify InfluxDB container is running: `sudo docker ps | grep influx`
- Check disk space: `df -h`

**Restore fails:**
- Verify backup file exists: `ls -lh ~/beeperKeeper/backups/influxdb/YYYY/MM/`
- Check restore logs: `tail -50 ~/beeperKeeper/backups/influx_restore.log`

**"Bucket already exists" error:**
- Delete the old bucket first (see "Deleting Temporary Buckets" above)

## Estimated Storage Usage

- **Per month compressed**: ~100-500MB (varies by sensor frequency)
- **10 years of backups**: ~12-60GB total
- **Uncompressed (when restored)**: 3-5x larger

## Best Practices

1. **Test restores periodically** - verify backups are working
2. **Clean up temp buckets** - don't leave analysis buckets running indefinitely
3. **Monitor disk space** - keep eye on `/home/YOUR_USERNAME/beeperKeeper/backups/`
4. **Document analysis** - keep notes on what you analyzed and findings
5. **External backups** - periodically copy backups to external storage/NAS

---

**Last Updated**: October 26, 2025
**System**: BeeperKeeper v2.0
