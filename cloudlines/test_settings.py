import os

# Base settings
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = 'test-secret-key-not-for-production'

DEBUG = True

ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'test_db.sqlite3'),
    }
}

STATIC_URL = '/static/'
MEDIA_URL = '/media/'

DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

DATE_INPUT_FORMATS = ['%d-%m-%Y']

# Import the rest of settings from main settings file
# (this must come after our overrides since settings.py tries to import local_settings)
from cloudlines.settings import *  # noqa

# Re-override what settings.py may have set
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'test_db.sqlite3'),
    }
}
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
STATIC_URL = '/static/'
