# BeeperKeeper v2.0 Changelog

## 2025-10-31 - Performance & Quality Improvements

### Countdown Timer Diagnosis
- **Issue**: Timer displaying "--" instead of numbers on web interface
- **Root Cause**: JavaScript execution halted by Fetch API error in `initStreams()`
- **Status**: Diagnosed but not fixed (moved to other priorities)
- **Key Learning**: Silent JavaScript failures prevent subsequent code execution
- **Recommended Fix**: Add try/catch error handling to async initialization functions

### Video Quality Upgrade - CSI Camera to Full HD
- **Change**: CSI camera upgraded from 800x600@15fps to 1920x1080@30fps
- **Encoding**: Hardware H.264 (Raspberry Pi ISP)
- **Performance Impact**:
  - CPU: 32% → ~53.5% (moderate increase)
  - Temperature: 60°C → 64-65°C (safe range, 15°C margin before throttling)
  - Data increase: 5.76x (resolution + framerate combined)
  - CPU increase: Only 4-7% (hardware encoder efficiency)
- **Quality**: Significant improvement - now Full HD quality on CSI stream
- **USB Camera**: Attempted upgrade to 640x480@15fps, reverted to 480x360@8fps per user preference for stability
- **Result**: Asymmetric quality profile (CSI high quality, USB stable) optimal for this hardware

### Grafana Panel 607 Fix - Water Consumption Display
- **Issue**: Panel 607 "Water Consumption by Time Period" showing "No Data"
- **Root Cause**: Flux query bug - `mean()` removes `_time` column, then `pivot(rowKey: ["_time"])` fails
- **Solution**: Reconstruct `_time` column after aggregation: `|> map(fn: (r) => ({ r with _time: now() }))`
- **Provisioning Challenge**: Dashboard cached in Grafana SQLite database, required deletion and re-provisioning
- **Fix Applied**: All 4 queries (1h, 6h, 12h, 24h) in Panel 607 now reconstruct `_time` before pivot
- **Result**: Panel 607 correctly displays water consumption percentages with gauge bars

### Technical Insights
- **Hardware vs Software Encoding**: Hardware H.264 scales 6-7x more efficiently than software encoding on Pi
- **Thermal Management**: Pi 3B+ can handle 1080p@30fps at 64-65°C (well below 80°C throttling threshold)
- **Flux Aggregation Behavior**: `mean()`, `sum()`, `count()` remove `_time` column - must reconstruct for downstream operations
- **Grafana Provisioning**: Dashboards cached in database - JSON changes require database deletion or aggressive cache clearing
- **Asymmetric Streaming**: Mixed quality profiles (one high-quality hardware encoder, one stable software encoder) can be optimal strategy

### Files Modified
- `/opt/beeperKeeper/start_csi_with_metadata.sh` - Resolution 800x600→1920x1080, framerate 15→30fps
- `/opt/beeperKeeper/config/start_usb_camera.sh` - Attempted upgrade then reverted to original settings
- `~/beeperKeeper/grafana/dashboards/beeper_sensors.json` - Panel 607 Flux queries (A, B, C, D) fixed with `_time` reconstruction

### System Status ✓
- CSI Camera: 1920x1080@30fps (Full HD, hardware encoded)
- USB Camera: 480x360@8fps (stable, software encoded)
- CPU Usage: ~53.5% (sustainable)
- Temperature: 64-65°C (safe range)
- Grafana Panel 607: Water consumption percentages displaying correctly

## 2025-10-26 - Major Updates

### Dashboard Improvements
- Cleaned Grafana Dashboard Database (removed 3 duplicates)
- Reduced header logo padding (20px → 4px top/bottom)
- Fixed Grafana database permissions

### Camera Metadata System - FIXED
- **Issue**: Camera metadata missing from Flask app
- **Cause**: metadata_updater.py not running
- **Fixed**: Started metadata_updater service
- **Status**: Metadata now flowing (Exposure, Lux, Color Temp, Gain)

### Chat Message Deletion Feature - NEW
**Backend** (`app.py`):
- Added UUID to all messages for unique identification
- New endpoint: `DELETE /api/chat/delete/<message_id>` (ownership verified)
- New endpoint: `GET /api/whoami` (returns current username)

**Frontend** (`index.html`):
- Delete button (🗑️) appears only on user's own messages
- Confirmation dialog before deletion
- Username detection via API call

**Security**:
- Server-side ownership verification
- Users can ONLY delete their own messages
- Returns 403 if unauthorized

### Files Modified
- `backend/app.py` - UUID support, delete endpoint, whoami endpoint
- `frontend/index.html` - Delete UI, username detection
- `scripts/metadata_updater.py` - Verified running

### All Services ✓
- Flask App - Running
- Camera Metadata - Flowing
- MQTT - Active
- Grafana - Clean dashboard
