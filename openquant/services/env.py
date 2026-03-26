from dotenv import load_dotenv, dotenv_values
import os
import sys

# fix directory issue
sys.path.insert(0, os.getcwd())

ENV_VALUES = {}


def _is_unit_testing() -> bool:
    return 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ


def _is_jesse_project() -> bool:
    return os.path.isfile('.env')


if _is_unit_testing():
    ENV_VALUES['POSTGRES_HOST'] = '127.0.0.1'
    ENV_VALUES['POSTGRES_NAME'] = 'jesse_db'
    ENV_VALUES['POSTGRES_PORT'] = '5432'
    ENV_VALUES['POSTGRES_USERNAME'] = 'jesse_user'
    ENV_VALUES['POSTGRES_PASSWORD'] = 'password'
    ENV_VALUES['REDIS_HOST'] = 'localhost'
    ENV_VALUES['REDIS_PORT'] = '6379'
    ENV_VALUES['REDIS_DB'] = 0
    ENV_VALUES['REDIS_PASSWORD'] = ''
    ENV_VALUES['APP_PORT'] = 3000
    ENV_VALUES['IS_DEV_ENV'] = 'TRUE'
    ENV_VALUES['LSP_PORT'] = 9001

if _is_jesse_project():
    # load env
    load_dotenv()

    # create and expose ENV_VALUES
    ENV_VALUES = dotenv_values('.env')

    # Override with actual environment variables (docker-compose sets these)
    for key in list(ENV_VALUES.keys()):
        env_val = os.environ.get(key)
        if env_val is not None:
            ENV_VALUES[key] = env_val

    # validation for existence of .env file
    if len(list(ENV_VALUES.keys())) == 0:
        print(
            '.env file is missing from within your local project. '
            'This usually happens when you\'re in the wrong directory. '
            '\n\nIf you haven\'t created a Jesse project yet, do that by running: \n'
            'jesse make-project {name}\n'
            'And then go into that project, and run the same command.'
        )
        os._exit(1)

    if not _is_unit_testing() and ENV_VALUES.get('PASSWORD', '') == '':
        raise EnvironmentError('You forgot to set the PASSWORD in your .env file')
else:
    # No .env file (e.g. Docker) — load from environment variables directly
    _ENV_KEYS = [
        'POSTGRES_HOST', 'POSTGRES_NAME', 'POSTGRES_PORT', 'POSTGRES_USERNAME', 'POSTGRES_PASSWORD',
        'REDIS_HOST', 'REDIS_PORT', 'REDIS_DB', 'REDIS_PASSWORD',
        'APP_PORT', 'PASSWORD', 'IS_DEV_ENV', 'LSP_PORT',
        'LICENSE_API_TOKEN', 'LIVE_PLUGIN_API_TOKEN',
    ]
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            ENV_VALUES[key] = val

    if not _is_unit_testing() and not ENV_VALUES:
        print('Warning: No .env file and no environment variables found.')



def is_dev_env() -> bool:
    return ENV_VALUES.get('IS_DEV_ENV', '').upper() == 'TRUE'
