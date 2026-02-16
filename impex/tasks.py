from celery import shared_task
from django.conf import settings
import requests
import urllib.parse
import logging

logger = logging.getLogger(__name__)


def _get_orch_headers():
    """Authenticate with the orchestrator and return request headers."""
    token_res = requests.post(
        url=urllib.parse.urljoin(settings.ORCH_URL, '/api-token-auth/'),
        data={'username': settings.ORCH_USER, 'password': settings.ORCH_PASS}
    )
    token_res.raise_for_status()
    return {
        'Content-Type': 'application/json',
        'Authorization': f"token {token_res.json()['token']}"
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_export_all(self, domain, user_token, account_id, file_name):
    """Run a full export via the orchestrator."""
    try:
        headers = _get_orch_headers()
        data = '{"domain": "%s", "token": "%s", "account": %d, "file_name": "%s"}' % (
            domain, user_token, account_id, file_name
        )
        response = requests.post(
            url=urllib.parse.urljoin(settings.ORCH_URL, '/api/tasks/export_all/'),
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'status_code': response.status_code}
    except Exception as exc:
        logger.error(f"Export all task failed: {exc}")
        raise self.retry(exc=exc)
