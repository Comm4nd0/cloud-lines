from celery import shared_task
from django.conf import settings as django_settings
from urllib.parse import urljoin
import requests
import logging

logger = logging.getLogger(__name__)


def _get_orch_headers():
    """Authenticate with the orchestrator and return request headers."""
    token_res = requests.post(
        url=urljoin(django_settings.ORCH_URL, '/api-token-auth/'),
        data={'username': django_settings.ORCH_USER, 'password': django_settings.ORCH_PASS}
    )
    token_res.raise_for_status()
    return {
        'Content-Type': 'application/json',
        'Authorization': f"token {token_res.json()['token']}"
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_custom_fields(self, domain, account_id, user_token):
    """Sync custom fields to the orchestrator after a field change."""
    try:
        headers = _get_orch_headers()
        data = '{"domain": "%s", "account": %s, "token": "%s"}' % (domain, account_id, user_token)
        response = requests.post(
            url=urljoin(django_settings.ORCH_URL, '/api/custom_fields/update_fields/'),
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success'}
    except Exception as exc:
        logger.error(f"Custom fields sync task failed: {exc}")
        raise self.retry(exc=exc)
