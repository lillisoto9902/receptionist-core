"""In-memory synthetic operational settings; never a usable database credential."""
import secrets


def environment():
    return {'RC_ENVIRONMENT':'test', 'ADMIN_API_TOKEN':secrets.token_urlsafe(32),
            'RC_DATABASE_HOST':'127.0.0.1','RC_DATABASE_PORT':'55432',
            'RC_DATABASE_NAME':'receptionist_core_test','RC_DATABASE_USER':'receptionist_core_test_app',
            'DATABASE_URL':'postgresql://receptionist_core_test_app:' + secrets.token_urlsafe(32) + '@127.0.0.1:55432/receptionist_core_test'}
