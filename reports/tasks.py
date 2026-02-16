from celery import shared_task
from django.conf import settings
from rest_framework.authtoken.models import Token
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
def run_census_report(self, queue_id, domain, user_token):
    """Run a census report via the orchestrator."""
    try:
        headers = _get_orch_headers()
        data = '{"queue_id": %d, "domain": "%s", "token": "%s"}' % (queue_id, domain, user_token)
        response = requests.post(
            url=f'{settings.ORCH_URL}/api/reports/census/',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'queue_id': queue_id}
    except Exception as exc:
        logger.error(f"Census report task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_all_report(self, queue_id, domain, user_token):
    """Run an 'all living' report via the orchestrator."""
    try:
        headers = _get_orch_headers()
        data = '{"queue_id": %d, "domain": "%s", "token": "%s"}' % (queue_id, domain, user_token)
        response = requests.post(
            url=f'{settings.ORCH_URL}/api/reports/all/',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'queue_id': queue_id}
    except Exception as exc:
        logger.error(f"All report task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_all_boo_report(self, queue_id, domain, user_token, prefix_type, breeder_prefix):
    """Run an 'all by breeder/owner' report via the orchestrator."""
    try:
        headers = _get_orch_headers()
        data = '{"queue_id": %d, "domain": "%s", "token": "%s", "boo": "%s", "prefix": "%s"}' % (
            queue_id, domain, user_token, prefix_type, breeder_prefix
        )
        response = requests.post(
            url=f'{settings.ORCH_URL}/api/reports/all_boo/',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'queue_id': queue_id}
    except Exception as exc:
        logger.error(f"All BOO report task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_fangr_report(self, queue_id, domain, account_id, year, breed_id, email, user_token):
    """Run a FANGR/UKGLE report via the orchestrator."""
    try:
        headers = _get_orch_headers()
        data = '{"queue_id": %d, "domain": "%s", "account": %d, "year": "%s", "breed": "%d", "email": "%s", "token": "%s"}' % (
            queue_id, domain, account_id, year, breed_id, email, user_token
        )
        response = requests.post(
            url=f'{settings.ORCH_URL}/api/reports/fangr/',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return {'status': 'success', 'queue_id': queue_id}
    except Exception as exc:
        logger.error(f"FANGR report task failed: {exc}")
        raise self.retry(exc=exc)
