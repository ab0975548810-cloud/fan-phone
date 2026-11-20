"""Access decisions for the opt-in test editor. No order or print writes."""
import hashlib
import os
import time

from flask import session


def fingerprint(row):
    # Include the verified public key, not the mutable user-assigned name.
    identity = row['credential_id'] + '.' + row['public_key']
    return hashlib.sha256(identity.encode('ascii')).hexdigest()


def enabled():
    return os.getenv('ADMIN_REEDIT_TEST_ENABLED') == 'true'


def allowed(service, identity):
    if not enabled() or not identity:
        return False
    permitted = os.getenv('ADMIN_REEDIT_TEST_CREDENTIAL_SHA256', '').split(',')
    if identity not in {value.strip() for value in permitted}:
        return False
    # Read current registration for every decision, including revocation checks.
    return any(fingerprint(row) == identity for row in service.registered_for_reedit())


def session_identity(service):
    if not session.get('logged_in') or session.get('auth_method') != 'passkey':
        return None
    if not 0 <= time.time() - session.get('reedit_verified_at', 0) < 900:
        return None
    identity = session.get('reedit_fingerprint')
    return identity if allowed(service, identity) else None
