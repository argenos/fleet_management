import logging

from fleet_management.db.ccu_store import CCUStore
from fleet_management.task_manager import TaskManager
from ropod.utils.config import read_yaml_file

from fleet_management.exceptions.config import InvalidConfig

logging.getLogger(__name__)


def load_version(config):
    version = config.get('version', None)
    if version not in (1, 2):
        raise InvalidConfig


def load_resources(config):
    resources = config.get('resources', None)
    if resources is None:
        raise InvalidConfig

    fleet = resources.get('fleet', None)
    if fleet is None:
        raise InvalidConfig

    infrastructure = resources.get('infrastructure', None)
    if infrastructure is None:
        logging.debug("No infrastructure resources added.")
    else:
        logging.debug(infrastructure)


def load_plugins(config):
    plugins = config.get('plugins', None)

    if plugins is None:
        logging.info("No plugins added.")

    for plugin, plugin_config in plugins.items():
        print(plugin)


def load_api(config):
    api = config.get('api', None)

    if api is None:
        logging.error("Missing API configuration. At least one API option must be configured")
        raise InvalidConfig

    # Check if we have any valid API config
    if not any(elem in ['zyre', 'ros', 'rest'] for elem in api.keys()):
        raise InvalidConfig

    zyre_config = api.get('zyre', None)
    if zyre_config is None:
        logging.debug('FMS missing Zyre API')
        raise InvalidConfig

    rest_config = api.get('rest', None)
    if rest_config is None:
        logging.debug('FMS missing REST API')

    ros_config = api.get('ros', None)
    if ros_config is None:
        logging.debug('FMS missing ROS API')


def load_config(config_file):
    config = read_yaml_file(config_file)
    return config


class Config(object):
    def __init__(self, config_file):
        config = load_config(config_file)
        self.__dict__.update(**config)

    def __str__(self):
        return str(self.__dict__)

    def configure_ccu_store(self):
        store_config = self.__dict__.get('ccu_store', dict())
        if not store_config:
            logging.info('Using default ccu_store config')
            store_config.update(dict(db_name='ropod_ccu_store', port=27017))
        else:
            store_config.update(db_name=store_config.get('db_name', 'ropod_ccu_store'))
            store_config.update(port=store_config.get('port', 27017))

        return CCUStore(**store_config)

    def configure_task_manager(self, db):
        task_manager_config = self.__dict__.get('task_manager', None)
        if task_manager_config is None:
            logging.info('Using default task manager config')
        else:
            api = self.__dict__.get('api')

        return TaskManager(db, api_config=api, plugins=[])

