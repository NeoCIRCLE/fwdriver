from os import getenv

CELERY_TASK_RESULT_EXPIRES = 3600
BROKER_URL = getenv("AMQP_URI")
