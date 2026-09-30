"""Persistent, privacy-preserving quota accounting for RunPod AI jobs."""

from dataclasses import dataclass
import hashlib
import hmac
import os
import uuid


CLIENT_LIMIT_24H = 5
IP_LIMIT_24H = 15
GLOBAL_LIMIT_24H = 60
ACTIVE_LIMIT = 2

QUOTA_MESSAGES = {
    'AI_DEVICE_DAILY_LIMIT': '今天的雲端 AI 去背額度已用完，簡單背景仍可使用通用去背，請稍後再試。',
    'AI_IP_DAILY_LIMIT': '此網路今天的雲端 AI 使用量已達上限，請稍後再試。',
    'AI_GLOBAL_DAILY_LIMIT': '今日雲端 AI 使用量已達安全上限，請稍後再試。',
    'AI_BUSY': 'AI 正在處理其他圖片，請稍後再試。',
}
QUOTA_UNAVAILABLE_MESSAGE = '雲端 AI 配額服務暫時無法使用，請稍後再試。'


class AiQuotaUnavailable(RuntimeError):
    code = 'AI_QUOTA_UNAVAILABLE'


class AiQuotaRejected(RuntimeError):
    def __init__(self, code):
        self.code = str(code or '')
        super().__init__(QUOTA_MESSAGES.get(self.code, '雲端 AI 暫時無法使用，請稍後再試。'))


@dataclass(frozen=True)
class AiQuotaReservation:
    request_id: str


def resolve_hash_secret():
    dedicated = (os.environ.get('AI_QUOTA_HASH_SECRET') or '').strip()
    if dedicated:
        return dedicated
    fallback = (os.environ.get('FLASK_SECRET_KEY') or '').strip()
    if fallback and os.environ.get('BENFUWAN_GENERATED_SECRET') != '1':
        return fallback
    return ''


def identity_hash(secret, namespace, raw_value):
    secret = str(secret or '')
    raw_value = str(raw_value or '')
    if not secret or not raw_value or namespace not in ('client', 'ip'):
        raise AiQuotaUnavailable('AI quota hash identity is unavailable')
    message = f'{namespace}:{raw_value}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


def _rpc_data(client, name, params=None):
    if client is None:
        raise AiQuotaUnavailable('Supabase quota client is unavailable')
    try:
        result = client.rpc(name, params or {}).execute()
        return result.data
    except AiQuotaUnavailable:
        raise
    except Exception as exc:
        raise AiQuotaUnavailable(f'AI quota RPC {name} failed') from exc


class PersistentAiQuota:
    """Calls service-role-only PostgreSQL functions; raw identities never leave Flask."""

    def __init__(self, client_getter, secret_getter=resolve_hash_secret):
        self._client_getter = client_getter
        self._secret_getter = secret_getter

    def _client(self):
        try:
            return self._client_getter()
        except Exception as exc:
            raise AiQuotaUnavailable('Supabase quota client is unavailable') from exc

    def reserve(self, client_id, ip_address):
        secret = self._secret_getter()
        request_id = str(uuid.uuid4())
        data = _rpc_data(self._client(), 'reserve_ai_usage', {
            'p_request_id': request_id,
            'p_client_hash': identity_hash(secret, 'client', client_id),
            'p_ip_hash': identity_hash(secret, 'ip', ip_address),
        })
        if not isinstance(data, dict):
            raise AiQuotaUnavailable('AI quota reservation returned invalid data')
        if data.get('reserved') is True:
            return AiQuotaReservation(request_id=request_id)
        code = str(data.get('code') or '')
        if code in QUOTA_MESSAGES:
            raise AiQuotaRejected(code)
        raise AiQuotaUnavailable('AI quota reservation was not created')

    def mark_submitted(self, reservation, runpod_job_id):
        ok = _rpc_data(self._client(), 'mark_ai_usage_submitted', {
            'p_request_id': reservation.request_id,
            'p_runpod_job_id': str(runpod_job_id or ''),
        })
        if ok is not True:
            raise AiQuotaUnavailable('AI quota submission was not recorded')

    def release(self, reservation):
        ok = _rpc_data(self._client(), 'release_ai_usage', {
            'p_request_id': reservation.request_id,
        })
        if ok is not True:
            raise AiQuotaUnavailable('AI quota reservation was not released')

    def finish(self, reservation, state):
        if state not in ('COMPLETED', 'FAILED'):
            raise ValueError('Invalid AI quota finish state')
        ok = _rpc_data(self._client(), 'finish_ai_usage', {
            'p_request_id': reservation.request_id,
            'p_state': state,
        })
        if ok is not True:
            raise AiQuotaUnavailable('AI quota final state was not recorded')

    def diagnostics(self):
        data = _rpc_data(self._client(), 'get_ai_usage_diagnostics')
        if not isinstance(data, dict):
            raise AiQuotaUnavailable('AI quota diagnostics returned invalid data')
        return {
            'client_limit_24h': CLIENT_LIMIT_24H,
            'ip_limit_24h': IP_LIMIT_24H,
            'global_limit_24h': GLOBAL_LIMIT_24H,
            'active_limit': ACTIVE_LIMIT,
            'global_used_24h': int(data.get('global_used_24h') or 0),
            'active_now': int(data.get('active_now') or 0),
        }


def unavailable_diagnostics():
    return {
        'client_limit_24h': CLIENT_LIMIT_24H,
        'ip_limit_24h': IP_LIMIT_24H,
        'global_limit_24h': GLOBAL_LIMIT_24H,
        'active_limit': ACTIVE_LIMIT,
        'global_used_24h': None,
        'active_now': None,
    }
