# analytics.py - Analytics Engine for ONGC Dashboard v2

from database import (get_analytics, get_daily_summary, get_weekly_summary,
                      get_monthly_summary, get_trend)


def build_analytics_report(tank_number=None):
    stats   = get_analytics(tank_number)
    daily   = get_daily_summary(tank_number)
    weekly  = get_weekly_summary(tank_number)
    monthly = get_monthly_summary(tank_number)

    for row in stats:
        tn = row['tank_number']
        row['pressure_trend']    = get_trend(tn, 'pressure')
        row['temperature_trend'] = get_trend(tn, 'temperature')
        row['flow_trend']        = get_trend(tn, 'flow')
        row['level_trend']       = get_trend(tn, 'level')

    return {
        'stats':       stats,
        'daily':       daily,
        'weekly':      weekly,
        'monthly':     monthly,
        'tank_filter': tank_number
    }
