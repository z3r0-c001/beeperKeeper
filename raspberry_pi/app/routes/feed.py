"""
Feed Routes Blueprint

ML feed detection, ROI management, and training endpoints.
"""
from flask import Blueprint, jsonify, request, Response, current_app
from app.extensions import limiter
import shutil
import os

feed_bp = Blueprint('feed', __name__, url_prefix='/api/feed')


def get_feed_service():
    """Get feed service from app config"""
    return current_app.config.get('feed_service')


@feed_bp.route('/calibration')
def get_feed_calibration():
    """Get current feed calibration values"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    config = feed_service.get_feed_config()
    if not config:
        return jsonify({'error': 'Could not read config'}), 500

    return jsonify({
        'full_y': config['full_y'],
        'empty_y': config['empty_y'],
        'range': abs(config['empty_y'] - config['full_y'])
    })


@feed_bp.route('/roi-image')
@limiter.limit("6 per minute")
def get_feed_roi_image():
    """Get current ROI image from camera"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    force_fresh = request.args.get('force_fresh', 'false').lower() == 'true'
    roi_jpeg = feed_service.get_roi_image(force_fresh=force_fresh)

    if roi_jpeg:
        return Response(roi_jpeg, mimetype='image/jpeg')
    return jsonify({'error': 'Could not capture ROI image'}), 500


@feed_bp.route('/full-frame')
def get_feed_full_frame():
    """Get full camera frame for ROI adjustment"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    frame_jpeg = feed_service.get_full_frame()
    if frame_jpeg:
        return Response(frame_jpeg, mimetype='image/jpeg')
    return jsonify({'error': 'Could not capture frame'}), 500


@feed_bp.route('/save-calibration', methods=['POST'])
def save_feed_calibration():
    """Save new calibration markers"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    full_y = int(request.json.get('full_y', 0))
    empty_y = int(request.json.get('empty_y', 0))

    if full_y >= empty_y:
        return jsonify({
            'success': False,
            'error': 'FULL_Y must be less than EMPTY_Y (Y increases downward)'
        }), 400

    if feed_service.save_feed_config(full_y=full_y, empty_y=empty_y):
        # Restart feed-monitor service
        import subprocess
        subprocess.run(['sudo', 'systemctl', 'restart', 'feed-monitor'],
                       capture_output=True, timeout=10)

        return jsonify({
            'success': True,
            'full_y': full_y,
            'empty_y': empty_y,
            'message': 'Calibration saved and feed-monitor restarted'
        })

    return jsonify({'success': False, 'error': 'Could not save config'}), 500


@feed_bp.route('/save-roi', methods=['POST'])
def save_roi_config():
    """
    Save new ROI coordinates.
    WARNING: This invalidates all training data and models.
    """
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    roi_x = int(request.json.get('x', 0))
    roi_y = int(request.json.get('y', 0))
    roi_width = int(request.json.get('width', 0))
    roi_height = int(request.json.get('height', 0))

    # Validate
    if roi_x < 0 or roi_y < 0 or roi_width < 10 or roi_height < 10:
        return jsonify({
            'success': False,
            'error': 'Invalid ROI coordinates (must be positive with minimum 10x10 size)'
        }), 400

    if roi_x + roi_width > 1920 or roi_y + roi_height > 1080:
        return jsonify({
            'success': False,
            'error': 'ROI exceeds frame bounds (1920x1080)'
        }), 400

    # Delete training data (invalidated by ROI change)
    cleanup_actions = []
    images_deleted = 0
    labels_deleted = 0

    if os.path.exists(feed_service.training_images_dir):
        images_deleted = len([f for f in os.listdir(feed_service.training_images_dir) if f.endswith('.jpg')])
        shutil.rmtree(feed_service.training_images_dir)
        os.makedirs(feed_service.training_images_dir, exist_ok=True)
        cleanup_actions.append(f"Deleted {images_deleted} training images")

    if os.path.exists(feed_service.training_labels_dir):
        labels_deleted = len([f for f in os.listdir(feed_service.training_labels_dir) if f.endswith('.json')])
        shutil.rmtree(feed_service.training_labels_dir)
        os.makedirs(feed_service.training_labels_dir, exist_ok=True)
        cleanup_actions.append(f"Deleted {labels_deleted} training labels")

    # Delete trained model
    model_path = '/opt/beeperKeeper/models/feed_model.tflite'
    if os.path.exists(model_path):
        os.remove(model_path)
        cleanup_actions.append("Deleted trained ML model")

    # Reset calibration markers to safe defaults
    safe_full_y = int(roi_height * 0.1)
    safe_empty_y = int(roi_height * 0.9)

    # Save config
    if feed_service.save_feed_config(
            roi_x=roi_x, roi_y=roi_y,
            roi_width=roi_width, roi_height=roi_height,
            full_y=safe_full_y, empty_y=safe_empty_y):

        # Clear cache
        feed_service.clear_cache()

        # Restart feed-monitor
        import subprocess
        subprocess.run(['sudo', 'systemctl', 'restart', 'feed-monitor'],
                       capture_output=True, timeout=10)

        return jsonify({
            'success': True,
            'roi': {'x': roi_x, 'y': roi_y, 'width': roi_width, 'height': roi_height},
            'cleanup_actions': cleanup_actions,
            'training_data_deleted': {'images': images_deleted, 'labels': labels_deleted},
            'calibration_reset': {'full_y': safe_full_y, 'empty_y': safe_empty_y},
            'warning': 'All training data and ML model deleted due to ROI change. Recalibration required.'
        })

    return jsonify({'success': False, 'error': 'Could not save config'}), 500


@feed_bp.route('/save-training-sample', methods=['POST'])
def save_training_sample():
    """Save a training sample for ML model"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    y_position = int(request.json.get('y_position', 0))
    percent_full = float(request.json.get('percent_full', 0))

    samples, error = feed_service.save_training_sample(y_position, percent_full)

    if error:
        return jsonify({'success': False, 'error': error}), 400

    return jsonify({
        'success': True,
        'samples_collected': samples
    })


@feed_bp.route('/training-progress')
def get_training_progress():
    """Get ML training dataset collection progress"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    progress = feed_service.get_training_progress()
    if progress:
        return jsonify(progress)
    return jsonify({'error': 'Could not get progress'}), 500


@feed_bp.route('/ml-predict')
def ml_predict_feed_level():
    """Run ML inference on current ROI image"""
    feed_service = get_feed_service()
    if not feed_service:
        return jsonify({'error': 'Feed service not available'}), 503

    result, error = feed_service.ml_predict()

    if error:
        return jsonify({'success': False, 'error': error}), 500

    return jsonify({
        'success': True,
        **result
    })
