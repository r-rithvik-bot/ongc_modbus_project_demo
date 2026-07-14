# modbus_reader.py - Modbus TCP Polling Engine for ONGC Dashboard v2

import threading
import time
import logging
from pymodbus.client import ModbusTcpClient
from config import (REGISTERS_PER_TANK, REG_PRESSURE_OFFSET, REG_TEMPERATURE_OFFSET,
                    REG_FLOW_OFFSET, REG_LEVEL_OFFSET, PRESSURE_SCALE, TEMPERATURE_SCALE,
                    FLOW_SCALE, LEVEL_SCALE, ALERT_PRESSURE_HIGH, ALERT_TEMPERATURE_HIGH,
                    ALERT_LEVEL_FULL, ALERT_LEVEL_EMPTY)
from database import save_reading, log_alert, get_recent_alert

logger = logging.getLogger(__name__)

# ── Shared State ───────────────────────────────────────────────────────
live_data  = {}
alerts     = []
_lock      = threading.Lock()
_stop_evt  = threading.Event()
_thread    = None
_connected = False
_client    = None


def _scale(raw, factor):
    return round(raw / factor, 2)


def _health(pressure, temperature, tank_level):
    if pressure > ALERT_PRESSURE_HIGH or temperature > ALERT_TEMPERATURE_HIGH:
        return 'CRITICAL'
    if tank_level > ALERT_LEVEL_FULL or tank_level < ALERT_LEVEL_EMPTY:
        return 'WARNING'
    return 'NORMAL'


def _build_alerts(tank, pressure, temperature, tank_level):
    result = []
    checks = [
        (pressure    > ALERT_PRESSURE_HIGH,  'HIGH_PRESSURE',
         f'Tank {tank}: Pressure {pressure} PSI > {ALERT_PRESSURE_HIGH} PSI', 'danger', pressure),
        (temperature > ALERT_TEMPERATURE_HIGH, 'HIGH_TEMPERATURE',
         f'Tank {tank}: Temperature {temperature}°C > {ALERT_TEMPERATURE_HIGH}°C', 'danger', temperature),
        (tank_level  > ALERT_LEVEL_FULL,     'TANK_FULL',
         f'Tank {tank}: Level {tank_level}% — Tank almost full', 'warning', tank_level),
        (tank_level  < ALERT_LEVEL_EMPTY,    'TANK_EMPTY',
         f'Tank {tank}: Level {tank_level}% — Tank nearly empty', 'warning', tank_level),
    ]
    for condition, atype, msg, level, val in checks:
        if condition:
            result.append({'tank': tank, 'type': atype, 'message': msg, 'level': level})
            # Log only if not recently logged (5-minute cooldown)
            if not get_recent_alert(tank, atype, minutes=5):
                log_alert(tank, atype, val)
    return result


def _poll_loop(host, port, slave_id, num_tanks, interval):
    global _connected, _client, live_data, alerts
    _client = ModbusTcpClient(host=host, port=port, timeout=3)

    while not _stop_evt.is_set():
        try:
            if not _client.is_socket_open():
                ok = _client.connect()
                with _lock:
                    _connected = ok
                if not ok:
                    time.sleep(interval)
                    continue

            new_alerts = []
            from datetime import datetime

            for tank in range(1, num_tanks + 1):
                base = (tank - 1) * REGISTERS_PER_TANK
                try:
                    resp = _client.read_holding_registers(address=base, count=REGISTERS_PER_TANK,
                                      device_id=slave_id)
                    if resp.isError():
                        with _lock:
                            if tank in live_data:
                                live_data[tank]['status'] = 'ERROR'
                        continue

                    r    = resp.registers
                    pres = _scale(r[REG_PRESSURE_OFFSET],    PRESSURE_SCALE)
                    temp = _scale(r[REG_TEMPERATURE_OFFSET], TEMPERATURE_SCALE)
                    flow = _scale(r[REG_FLOW_OFFSET],        FLOW_SCALE)
                    lvl  = _scale(r[REG_LEVEL_OFFSET],       LEVEL_SCALE)
                    ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    new_alerts.extend(_build_alerts(tank, pres, temp, lvl))

                    with _lock:
                        if tank not in live_data:
                            live_data[tank] = {
                                'pressure_history': [], 'temperature_history': [],
                                'flow_history': [],    'level_history': [],
                                'timestamps': []
                            }
                        live_data[tank].update({
                            'pressure': pres, 'temperature': temp,
                            'flow_rate': flow, 'tank_level': lvl,
                            'status': 'ONLINE', 'health': _health(pres, temp, lvl),
                            'last_updated': ts
                        })
                        for key, val in [('pressure_history', pres),
                                         ('temperature_history', temp),
                                         ('flow_history', flow),
                                         ('level_history', lvl)]:
                            live_data[tank][key].append(val)
                            if len(live_data[tank][key]) > 60:
                                live_data[tank][key].pop(0)
                        live_data[tank]['timestamps'].append(ts)
                        if len(live_data[tank]['timestamps']) > 60:
                            live_data[tank]['timestamps'].pop(0)

                    save_reading(tank, pres, temp, flow, lvl)

                except Exception as ex:
                    logger.error(f'Tank {tank} read error: {ex}')
                    with _lock:
                        if tank in live_data:
                            live_data[tank]['status'] = 'ERROR'

            with _lock:
                alerts     = new_alerts
                _connected = True

        except Exception as ex:
            logger.error(f'Poller error: {ex}')
            with _lock:
                _connected = False
            try: _client.close()
            except: pass

        time.sleep(interval)

    try: _client.close()
    except: pass
    with _lock:
        _connected = False


def start_polling(host, port, slave_id, num_tanks, interval):
    global _thread, _stop_evt, live_data, alerts
    stop_polling()
    live_data  = {}
    alerts     = []
    _stop_evt  = threading.Event()
    _thread    = threading.Thread(
        target=_poll_loop, args=(host, port, slave_id, num_tanks, interval),
        daemon=True, name='ModbusPoller'
    )
    _thread.start()
    logger.info(f'Modbus polling started → {host}:{port} | tanks={num_tanks} | interval={interval}s')


def stop_polling():
    global _thread
    _stop_evt.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    _thread = None


def get_live_data():
    with _lock: return dict(live_data)

def get_alerts():
    with _lock: return list(alerts)

def is_connected():
    with _lock: return _connected








