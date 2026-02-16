from celery import shared_task
from django.conf import settings
import requests
import logging

logger = logging.getLogger(__name__)


def _get_orch_headers():
    """Authenticate with the orchestrator and return request headers."""
    token_res = requests.post(
        url=f'{settings.ORCH_URL}/api-token-auth/',
        data={'username': settings.ORCH_USER, 'password': settings.ORCH_PASS}
    )
    token_res.raise_for_status()
    return {
        'Content-Type': 'application/json',
        'Authorization': f"token {token_res.json()['token']}"
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def provision_large_tier(self, queue_id):
    """Trigger the orchestrator to build a new large-tier instance."""
    try:
        headers = _get_orch_headers()
        data = '{"queue_id": %d}' % queue_id
        response = requests.post(
            url=f'{settings.ORCH_URL}/api/tasks/new_large_tier/',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'queue_id': queue_id}
    except Exception as exc:
        logger.error(f"Large tier provisioning task failed: {exc}")
        raise self.retry(exc=exc)
