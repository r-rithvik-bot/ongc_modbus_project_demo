# config.py - ONGC Dashboard v2 Configuration

import os

# ── Flask ──────────────────────────────────────────────────────────────
SECRET_KEY = "ONGC_MODBUS_PROJECT_2026"
DEBUG      = True

# ── Database ───────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(__file__)
DATABASE_PATH = os.path.join(BASE_DIR, 'database', 'ongc_data.db')

# ── Modbus Defaults ────────────────────────────────────────────────────
DEFAULT_MODBUS_HOST     = '127.0.0.1'
DEFAULT_MODBUS_PORT     = 1502
DEFAULT_SLAVE_ID        = 1
DEFAULT_REFRESH_INTERVAL = 2
DEFAULT_NUM_TANKS       = 1

# ── Register Layout ────────────────────────────────────────────────────
REGISTERS_PER_TANK      = 4
REG_PRESSURE_OFFSET     = 0
REG_TEMPERATURE_OFFSET  = 1
REG_FLOW_OFFSET         = 2
REG_LEVEL_OFFSET        = 3

# ── Alert Thresholds ───────────────────────────────────────────────────
ALERT_PRESSURE_HIGH     = 145
ALERT_TEMPERATURE_HIGH  = 45
ALERT_LEVEL_FULL        = 90
ALERT_LEVEL_EMPTY       = 20

# ── Scaling Factors ────────────────────────────────────────────────────
PRESSURE_SCALE    = 10.0
TEMPERATURE_SCALE = 10.0
FLOW_SCALE        = 10.0
LEVEL_SCALE       = 10.0

# ── AI Settings ────────────────────────────────────────────────────────
AI_MIN_READINGS   = 50    # minimum readings before AI activates
AI_PREDICT_STEPS  = 30    # how many future points to predict

# ── Email Alert Cooldown ───────────────────────────────────────────────
EMAIL_COOLDOWN_MINUTES = 5
