from celery import shared_task
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from json import dumps
import requests
import urllib.parse
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_data_validator(self, data_path, file_name, domain, dv_q_id, user_token):
    """Run data validation via the metrics service."""
    try:
        data = {
            'data_path': data_path,
            'file_name': file_name,
            'domain': domain,
            'dv_q_id': dv_q_id,
            'token': user_token
        }
        response = requests.post(
            urllib.parse.urljoin(settings.METRICS_URL, "/api/metrics/data_validator/"),
            json=dumps(data, cls=DjangoJSONEncoder)
        )
        response.raise_for_status()
        return {'status': 'success'}
    except Exception as exc:
        logger.error(f"Data validator task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_coi(self, data_path, file_name, domain, user_token):
    """Run COI calculation via the metrics service."""
    try:
        data = {
            'data_path': data_path,
            'file_name': file_name,
            'domain': domain,
            'token': user_token
        }
        response = requests.post(
            urllib.parse.urljoin(settings.METRICS_URL, "/api/metrics/coi/"),
            json=dumps(data, cls=DjangoJSONEncoder)
        )
        response.raise_for_status()
        return {'status': 'success'}
    except Exception as exc:
        logger.error(f"COI task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_kinship(self, mother_id, father_id, data_path, file_name, domain, kin_q_id, user_token):
    """Run kinship calculation via the metrics service."""
    try:
        data = {
            'data_path': data_path,
            'file_name': file_name,
            'domain': domain,
            'kin_q_id': kin_q_id,
            'token': user_token
        }
        response = requests.post(
            urllib.parse.urljoin(settings.METRICS_URL, f'/api/metrics/{mother_id}/{father_id}/kinship/'),
            json=dumps(data, cls=DjangoJSONEncoder),
            stream=True
        )
        response.raise_for_status()
        return {'status': 'success', 'status_code': response.status_code}
    except Exception as exc:
        logger.error(f"Kinship task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_mean_kinship(self, data_path, file_name, domain, user_token):
    """Run mean kinship calculation via the metrics service."""
    try:
        data = {
            'data_path': data_path,
            'file_name': file_name,
            'domain': domain,
            'token': user_token
        }
        response = requests.post(
            urllib.parse.urljoin(settings.METRICS_URL, '/api/metrics/mean_kinship/'),
            json=dumps(data, cls=DjangoJSONEncoder),
            stream=True
        )
        response.raise_for_status()
        return {'status': 'success'}
    except Exception as exc:
        logger.error(f"Mean kinship task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_stud_advisor(self, data_path, file_name, domain, pedigree_id,
                     pedigree_mk, breed_mean_coi, breed_mk_threshold,
                     user_token, queue_id):
    """Run stud advisor calculation via the metrics service."""
    try:
        data = {
            'data_path': data_path,
            'file_name': file_name,
            'domain': domain,
            'pedigree_id': pedigree_id,
            'pedigree_mk': pedigree_mk,
            'pedigree_breed_mean_coi': breed_mean_coi,
            'pedigree_breed_mk_threshold': breed_mk_threshold,
            'token': user_token,
            'queue_id': queue_id
        }
        response = requests.post(
            urllib.parse.urljoin(settings.METRICS_URL, '/api/metrics/stud_advisor/'),
            json=dumps(data, cls=DjangoJSONEncoder),
            stream=True
        )
        response.raise_for_status()
        return {'status': 'success', 'status_code': response.status_code}
    except Exception as exc:
        logger.error(f"Stud advisor task failed: {exc}")
        raise self.retry(exc=exc)
