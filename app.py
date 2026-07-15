# app.py - ONGC Industrial Modbus TCP Monitoring Dashboard v2

import csv
import io
import logging
import threading
from datetime  import datetime, timedelta
from functools import wraps
from flask     import (Flask, render_template, request, redirect,
                       url_for, jsonify, session, Response, flash)
from werkzeug.security import check_password_hash

from config   import (DEFAULT_MODBUS_HOST, DEFAULT_MODBUS_PORT, DEFAULT_SLAVE_ID,
                      DEFAULT_REFRESH_INTERVAL, DEFAULT_NUM_TANKS)
from database import (init_db, init_users_table,
                      get_history, get_all_for_export, save_config, load_config,
                      get_user_by_username, get_event_log, log_event)
from modbus_reader import start_polling, stop_polling, get_live_data, get_alerts, is_connected
from analytics     import build_analytics_report
from ai_predictor  import train_models, get_full_ai_report, start_ai_background

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

app            = Flask(__name__)
app.secret_key = 'ONGC_MODBUS_PROJECT_2026'
app.permanent_session_lifetime = timedelta(minutes=30)

# ── Bootstrap ──────────────────────────────────────────────────────────
init_db()
init_users_table()


# ── Auth Decorators ────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'Admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Home ───────────────────────────────────────────────────────────────
@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


# ── Login / Logout ─────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        user     = get_user_by_username(username)
        if user and check_password_hash(user['password'], password):
            session.permanent   = bool(remember)
            session['username'] = user['username']
            session['role']     = user['role']
            log_event(username, 'LOGIN', f'Role: {user["role"]}')
            flash('Login Successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid Username or Password', 'danger')
        return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    username = session.get('username', 'unknown')
    log_event(username, 'LOGOUT')
    session.pop('username', None)
    session.pop('role', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


# ── Dashboard ──────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    num_tanks = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    interval  = int(load_config('interval',  DEFAULT_REFRESH_INTERVAL))
    host      = load_config('host', DEFAULT_MODBUS_HOST)
    port      = load_config('port', DEFAULT_MODBUS_PORT)
    return render_template('dashboard.html',
                           num_tanks=num_tanks, interval=interval,
                           host=host, port=port)


# ── Live API ───────────────────────────────────────────────────────────
@app.route('/api/live')
@login_required
def api_live():
    data = get_live_data()
    return jsonify({
        'connected': is_connected(),
        'alerts':    get_alerts(),
        'tanks':     {str(k): v for k, v in data.items()},
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


# ── Configuration ──────────────────────────────────────────────────────
@app.route('/config', methods=['GET', 'POST'])
@admin_required
def config():
    if request.method == 'POST':
        host      = request.form.get('host',      DEFAULT_MODBUS_HOST)
        port      = int(request.form.get('port',  DEFAULT_MODBUS_PORT))
        slave_id  = int(request.form.get('slave_id',  DEFAULT_SLAVE_ID))
        interval  = int(request.form.get('interval',  DEFAULT_REFRESH_INTERVAL))
        num_tanks = int(request.form.get('num_tanks', DEFAULT_NUM_TANKS))

        for k, v in [('host', host), ('port', port), ('slave_id', slave_id),
                     ('interval', interval), ('num_tanks', num_tanks)]:
            save_config(k, v)

        start_polling(host, port, slave_id, num_tanks, interval)
        log_event(session['username'], 'CONFIG_CHANGED',
                  f'host={host} port={port} tanks={num_tanks}')
        flash('Configuration saved. Modbus polling restarted.', 'success')
        return redirect(url_for('dashboard'))

    cfg = {
        'host':      load_config('host',      DEFAULT_MODBUS_HOST),
        'port':      load_config('port',      DEFAULT_MODBUS_PORT),
        'slave_id':  load_config('slave_id',  DEFAULT_SLAVE_ID),
        'interval':  load_config('interval',  DEFAULT_REFRESH_INTERVAL),
        'num_tanks': load_config('num_tanks', DEFAULT_NUM_TANKS),
    }
    return render_template('config.html', cfg=cfg)


# ── History ────────────────────────────────────────────────────────────
@app.route('/history')
@login_required
def history():
    tank_number = request.args.get('tank_number', type=int)
    date_filter = request.args.get('date_filter', '')
    time_filter = request.args.get('time_filter', '')
    num_tanks   = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    records     = get_history(tank_number=tank_number,
                              date_filter=date_filter or None,
                              time_filter=time_filter or None, limit=200)
    return render_template('history.html', records=records, num_tanks=num_tanks,
                           tank_filter=tank_number,
                           date_filter=date_filter, time_filter=time_filter)


# ── Analytics ──────────────────────────────────────────────────────────
@app.route('/analytics')
@login_required
def analytics():
    tank_number = request.args.get('tank_number', type=int)
    num_tanks   = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    report      = build_analytics_report(tank_number)
    return render_template('analytics.html', report=report,
                           num_tanks=num_tanks, tank_filter=tank_number)


# ── AI Predictive Maintenance ──────────────────────────────────────────
@app.route('/ai')
@login_required
def ai_page():
    num_tanks   = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    tank_number = request.args.get('tank_number', 1, type=int)
    ai_report   = get_full_ai_report(tank_number)
    first_param = list(ai_report.values())[0]
    if first_param.get('status') == 'collecting':
        threading.Thread(target=train_models, args=(tank_number,), daemon=True).start()
    return render_template('ai.html', ai_report=ai_report,
                           num_tanks=num_tanks, tank_number=tank_number)


@app.route('/api/ai/<int:tank_number>/train', methods=['POST'])
@admin_required
def ai_train(tank_number):
    result = train_models(tank_number)
    return jsonify(result)


@app.route('/api/ai/<int:tank_number>/<param>')
@login_required
def ai_predict_api(tank_number, param):
    from ai_predictor import predict
    result = predict(tank_number, param)
    return jsonify(result)


# ── Reports ────────────────────────────────────────────────────────────
@app.route('/reports')
@admin_required
def reports():
    num_tanks = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    return render_template('reports.html', num_tanks=num_tanks)


@app.route('/reports/csv')
@admin_required
def download_csv():
    tank_number = request.args.get('tank_number', type=int)
    records     = get_all_for_export(tank_number)
    output      = io.StringIO()
    writer      = csv.DictWriter(output, fieldnames=[
        'id', 'timestamp', 'tank_number',
        'pressure', 'temperature', 'flow_rate', 'tank_level'])
    writer.writeheader()
    writer.writerows(records)
    output.seek(0)
    log_event(session['username'], 'CSV_EXPORT',
              f'tank={tank_number or "all"} rows={len(records)}')
    filename = f"ongc_tank_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.route('/reports/pdf')
@admin_required
def download_pdf():
    tank_number = request.args.get('tank_number', type=int)
    num_tanks   = int(load_config('num_tanks', DEFAULT_NUM_TANKS))
    records     = get_all_for_export(tank_number)
    report      = build_analytics_report(tank_number)
    log_event(session['username'], 'PDF_EXPORT',
              f'tank={tank_number or "all"}')
    return render_template('pdf_report.html', records=records[:200],
                           report=report, tank_filter=tank_number,
                           num_tanks=num_tanks,
                           generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


# ── Event Log ──────────────────────────────────────────────────────────
@app.route('/events')
@login_required
def events():
    logs = get_event_log(limit=300)
    return render_template('events.html', logs=logs)


# ── Disconnect ─────────────────────────────────────────────────────────
@app.route('/disconnect')
@admin_required
def disconnect():
    stop_polling()
    log_event(session['username'], 'DISCONNECT', 'Modbus polling stopped')
    flash('Modbus polling stopped', 'warning')
    return redirect(url_for('config'))


# ── Auto-resume polling on startup ─────────────────────────────────────
_sh = load_config('host')
_sp = load_config('port')
_ss = load_config('slave_id')
_sn = load_config('num_tanks')
_si = load_config('interval')

if all([_sh, _sp, _ss, _sn, _si]):
    start_polling(_sh, int(_sp), int(_ss), int(_sn), int(_si))
    start_ai_background(int(_sn))


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)