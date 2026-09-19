"""Synthetic company configuration; no credentials stored in fixtures."""
from app import main


def configuration(**overrides):
    services = {
        name.replace('_', '-'): {**service, 'keywords': [name.replace('_', ' ')]}
        for name, service in main.SERVICES.items()
    }
    services['coloring']['keywords'] = ['color', 'dye', 'highlight']
    result = dict(main.BUSINESS_SETTINGS)
    result.pop('deposits_enabled')
    result.pop('notifications_enabled')
    result.update(business_name='Synthetic company', contact_email='', contact_phone='',
                  greeting='Synthetic greeting', active=True, opening='09:00', closing='17:00',
                  interval_minutes=30, services=services)
    result.update(overrides)
    return result
