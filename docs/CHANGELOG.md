# BeeperKeeper v2.0 Changelog

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
