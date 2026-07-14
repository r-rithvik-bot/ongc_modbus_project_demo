# ai_predictor.py - Scikit-learn Predictive Maintenance for ONGC Dashboard v2

import threading
import logging
import numpy as np
from datetime import datetime, timedelta
from database import get_tank_readings_for_ai, count_readings, save_prediction
from config import AI_MIN_READINGS, AI_PREDICT_STEPS

logger = logging.getLogger(__name__)

# ── Model store: {(tank, parameter): trained_model_dict} ──────────────
_models      = {}
_models_lock = threading.Lock()

PARAMETERS = ['pressure', 'temperature', 'flow', 'level']


def _make_features(values, window=10):
    """Convert raw values list into (X, y) supervised learning arrays."""
    X, y = [], []
    for i in range(window, len(values)):
        X.append(values[i - window:i])
        y.append(values[i])
    return np.array(X), np.array(y)


def train_models(tank_number):
    """
    Train a LinearRegression model for each parameter of a given tank.
    Returns a status dict.
    """
    try:
        from sklearn.linear_model import LinearRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import mean_absolute_error
    except ImportError:
        logger.error('scikit-learn not installed')
        return {'status': 'error', 'message': 'scikit-learn not installed'}

    count = count_readings(tank_number)
    if count < AI_MIN_READINGS:
        return {
            'status': 'insufficient',
            'readings': count,
            'needed': AI_MIN_READINGS,
            'message': f'Need {AI_MIN_READINGS - count} more readings to activate AI'
        }

    trained = {}
    for param in PARAMETERS:
        rows   = get_tank_readings_for_ai(tank_number, param, limit=1000)
        values = [r['value'] for r in rows]

        if len(values) < 12:
            continue

        window = min(10, len(values) // 5)
        X, y   = _make_features(values, window=window)
        if len(X) < 5:
            continue

        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)

        model  = LinearRegression()
        model.fit(X_sc, y)

        y_pred = model.predict(X_sc)
        mae    = round(mean_absolute_error(y, y_pred), 3)

        trained[param] = {
            'model':      model,
            'scaler':     scaler,
            'window':     window,
            'last_vals':  values[-window:],
            'mae':        mae,
            'trained_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'n_samples':  len(values)
        }

    with _models_lock:
        _models[tank_number] = trained

    logger.info(f'AI models trained for Tank {tank_number}: {list(trained.keys())}')
    return {'status': 'ok', 'params': list(trained.keys())}


def predict(tank_number, param, steps=None):
    """
    Predict future values for a given tank/parameter.
    Returns dict with predictions, confidence, health score etc.
    """
    if steps is None:
        steps = AI_PREDICT_STEPS

    with _models_lock:
        tank_models = _models.get(tank_number, {})
        info        = tank_models.get(param)

    if info is None:
        count = count_readings(tank_number)
        return {
            'status':   'collecting',
            'readings': count,
            'needed':   AI_MIN_READINGS,
            'message':  f'Collecting data… {count}/{AI_MIN_READINGS} readings'
        }

    model     = info['model']
    scaler    = info['scaler']
    window    = info['window']
    last_vals = list(info['last_vals'])
    mae       = info['mae']

    predictions = []
    current     = list(last_vals)

    for i in range(steps):
        X_in = np.array(current[-window:]).reshape(1, -1)
        X_sc = scaler.transform(X_in)
        pred = float(model.predict(X_sc)[0])
        predictions.append(round(pred, 2))
        current.append(pred)

    # ── Derived indicators ─────────────────────────────────────────────
    avg_pred      = round(np.mean(predictions), 2)
    max_pred      = round(np.max(predictions), 2)
    min_pred      = round(np.min(predictions), 2)
    trend_slope   = round(float(np.polyfit(range(len(predictions)), predictions, 1)[0]), 4)

    # Failure probability — simple linear threshold approach
    from config import ALERT_PRESSURE_HIGH, ALERT_TEMPERATURE_HIGH, ALERT_LEVEL_FULL
    thresholds = {
        'pressure':    ALERT_PRESSURE_HIGH,
        'temperature': ALERT_TEMPERATURE_HIGH,
        'level':       ALERT_LEVEL_FULL,
        'flow':        999
    }
    threshold     = thresholds.get(param, 999)
    exceed_count  = sum(1 for p in predictions if p > threshold)
    fail_prob     = round((exceed_count / steps) * 100, 1)

    # Health score (100 = perfect, 0 = critical)
    current_val   = last_vals[-1] if last_vals else avg_pred
    if threshold < 999:
        health_score = max(0, round(100 - (current_val / threshold) * 100, 1))
    else:
        health_score = 85.0

    # Maintenance recommendation
    if fail_prob > 60:
        recommendation = 'Immediate inspection required'
        rul_hours      = 2
    elif fail_prob > 30:
        recommendation = 'Schedule maintenance within 24 hours'
        rul_hours      = 24
    elif trend_slope > 0.5:
        recommendation = 'Monitor closely — rising trend detected'
        rul_hours      = 72
    else:
        recommendation = 'System operating normally'
        rul_hours      = 720

    # Time labels for prediction horizon
    now    = datetime.now()
    labels = [(now + timedelta(minutes=2 * i)).strftime('%H:%M') for i in range(1, steps + 1)]

    # Save 1-hour and 24-hour predictions to history
    if len(predictions) >= 30:
        save_prediction(tank_number, param, predictions[29], 60)

    return {
        'status':         'ok',
        'predictions':    predictions,
        'labels':         labels,
        'avg_predicted':  avg_pred,
        'max_predicted':  max_pred,
        'min_predicted':  min_pred,
        'trend_slope':    trend_slope,
        'failure_prob':   fail_prob,
        'health_score':   health_score,
        'recommendation': recommendation,
        'rul_hours':      rul_hours,
        'mae':            mae,
        'trained_at':     info['trained_at'],
        'n_samples':      info['n_samples'],
        'param':          param
    }


def get_full_ai_report(tank_number):
    """Get predictions for all parameters of a tank."""
    result = {}
    for param in PARAMETERS:
        result[param] = predict(tank_number, param)
    return result


# ── Background daily retraining ────────────────────────────────────────
def _retrain_loop(num_tanks, interval_hours=24):
    while True:
        import time
        time.sleep(interval_hours * 3600)
        logger.info('AI: starting daily retraining...')
        for t in range(1, num_tanks + 1):
            train_models(t)
        logger.info('AI: daily retraining complete')


def start_ai_background(num_tanks):
    t = threading.Thread(
        target=_retrain_loop, args=(num_tanks,),
        daemon=True, name='AIRetrainer'
    )
    t.start()
