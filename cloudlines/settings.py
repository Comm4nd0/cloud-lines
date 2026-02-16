import os

try:
    from .local_settings import *
except ImportError:
    pass

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

# Application definition

INSTALLED_APPS = [
    'cloud_lines',
    'pedigree',
    'breeder',
    'breed',
    'breed_group',
    'account',
    'support',
    'impex',
    'approvals',
    'metrics',
    'boltons',
    'birth_notifications',
    'memberships',
    'reports',
    'widget_tweaks',
    'django_s3_storage',
    'storages',
    'django_extensions',
    'rest_framework',
    'django_filters',
    'django_celery_beat',
    'rest_framework.authtoken',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'cloudlines.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'account.views.site_mode',
            ],
        },
    },
]

WSGI_APPLICATION = 'cloudlines.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'PAGE_SIZE': 100,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
    },
}

# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-gb'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = False

LOGIN_REDIRECT_URL = '/dashboard'

DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

BOLTON_API_URL = "https://cloud-lines.com/api/bolton/"

TEST_STRIPE_DOMAINS = ['localhost:8000', '127.0.0.1:8000', 'development.cloud-lines.com', 'test.cloud-lines.com', 'demo.cloud-lines.com', 'poultrydemo.cloud-lines.com']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Celery Configuration
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# ---------------------------------------------------------------------------
# Email Configuration (SES)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
# When using SES set EMAIL_BACKEND=django_ses.SESBackend
AWS_SES_REGION_NAME = os.environ.get('AWS_SES_REGION_NAME', 'eu-west-1')
AWS_SES_REGION_ENDPOINT = os.environ.get('AWS_SES_REGION_ENDPOINT', 'email.eu-west-1.amazonaws.com')

# ---------------------------------------------------------------------------
# Database Configuration (environment-based override)
# ---------------------------------------------------------------------------
if os.environ.get('DATABASE_URL') or os.environ.get('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'cloudlines'),
            'USER': os.environ.get('DB_USER', 'cloudlines'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'db'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
