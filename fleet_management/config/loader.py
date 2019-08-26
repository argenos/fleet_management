import logging

from importlib_resources import open_text
from mrs.robot import Robot
from mrs.task_allocation.auctioneer import Auctioneer
from ropod.utils.config import read_yaml_file, get_config
from ropod.utils.logging.config import config_logger

from fleet_management.db.ccu_store import CCUStore, initialize_robot_db
from fleet_management.exceptions.config import InvalidConfig
from fleet_management.resource_manager import ResourceManager
from fleet_management.resources.infrastructure.elevators.interface import ElevatorManager
from fleet_management.task.monitor import TaskMonitor
from fleet_management.task_manager import TaskManager
from fleet_management.plugins.task_planner import TaskPlannerInterface

from fleet_management.config.config import plugin_factory
from fleet_management.config.config import configure


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


class Config(dict):

    def __init__(self, config_file=None):
        super().__init__()
        if config_file is None:
            config = _load_default_config()
        else:
            config = _load_file(config_file)

        self.update(**config)


def _load_default_config():
    config_file = open_text('fleet_management.config.default', 'config.yaml')
    config = get_config(config_file)
    return config


def _load_file(config_file):
    config = read_yaml_file(config_file)
    return config


default_config = Config()
default_logging_config = default_config.pop('logger')


class Configurator(object):

    def __init__(self, config_file=None, logger=True, **kwargs):
        self.logger = logging.getLogger('fms.config')
        self._builder = configure
        self._plugin_factory = plugin_factory

        self._config_params = Config(config_file)

        if logger:
            log_file = kwargs.get('log_file', None)
            self.configure_logger(filename=log_file)

    def configure(self):
        components = self._builder.configure(self._config_params)

        self._api = components.get('api')
        self._ccu_store = components.get('ccu_store')

    def __str__(self):
        return str(self._config_params)

    def configure_logger(self, logger_config=None, filename=None):
        if logger_config is not None:
            logging.info("Loading logger configuration from file: %s ", logger_config)
            config_logger(logger_config, filename=filename)
        elif 'logger' in self._config_params:
            logging.info("Using FMS logger configuration")
            fms_logger_config = self._config_params.get('logger', None)
            logging.config.dictConfig(fms_logger_config)
        else:
            logging.info("Using default ropod config...")
            config_logger(filename=filename)

    @property
    def api(self):
        if self._api:
            return self._api
        else:
            return self._builder.configure_component('api', self._config_params.get('api'))

    @property
    def ccu_store(self):
        if self._ccu_store:
            return self._ccu_store
        else:
            return self._builder.configure_component('ccu_store', self._config_params.get('ccu_store'))

    def configure_task_manager(self, db):
        task_manager_config = self._config_params.get('task_manager', None)
        if task_manager_config is None:
            self.logger.info('Using default task manager config')
        else:
            api = self._config_params.get('api')

        return TaskManager(db, api_config=self.api, plugins=[])

    def configure_resource_manager(self, db):
        rm_config = self._config_params.get('resource_manager', None)
        resources = self._config_params.get('resources', None)
        if rm_config is None:
            self.logger.info('Using default resource manager config')
        else:
            api = self._config_params.get('api')

        elevator_mgr_api_config = self._config_params.get('elevator_manager', None)
        monitoring_config = self._config_params.get('elevator_monitor', None)
        interface_config = self._config_params.get('elevator_interface', None)
        elevator_mgr = ElevatorManager.from_config(db, self.api, api_config=elevator_mgr_api_config,
                                                   monitoring_config=monitoring_config,
                                                   interface_config=interface_config)
        elevator_mgr.add_elevator(1)

        fleet_monitor_config = self._config_params.get('fleet_monitor', None)

        resource_mgr = ResourceManager(resources, ccu_store=db, api_config=self.api,
                                       plugins=[elevator_mgr], fleet_monitor_config=fleet_monitor_config)

        return resource_mgr

    def configure_plugins(self, ccu_store):
        logging.info("Configuring FMS plugins...")
        plugin_config = self._config_params.get('plugins')
        if plugin_config is None:
            self.logger.debug("Found no plugins in the configuration file.")
            return None

        # TODO add conditions to only configure plugins listed in the config file
        osm_bridge, path_planner, subarea_monitor = plugin_factory.configure('osm', **plugin_config.get('osm'))
        task_planner = self.configure_task_planner()
        auctioneer = self.configure_auctioneer(ccu_store)
        task_monitor = self.configure_task_monitor(ccu_store)
        return {'osm_bridge': osm_bridge, 'path_planner': path_planner, 'task_planner': task_planner,
                'task_monitor': task_monitor, 'auctioneer': auctioneer}

    def configure_task_planner(self):
        planner_config = self._config_params.get('plugins').get('task_planner', None)
        if planner_config is None:
            return None
        else:
            self.logger.info("Configuring task planner...")

        task_planner = TaskPlannerInterface(planner_config)
        return task_planner

    def configure_task_monitor(self, ccu_store):
        self.logger.info("Configuring task monitor")
        task_monitor_config = self._config_params.get('plugins').get('task_monitor', None)

        if task_monitor_config is None:
            return None

        task_monitor = TaskMonitor(ccu_store)
        return task_monitor

    def configure_auctioneer(self, ccu_store=None):
        allocation_config = self._config_params.get("plugins").get("task_allocation")
        auctioneer_config = self._config_params.get("plugins").get("auctioneer")
        auctioneer_config = {** allocation_config, ** auctioneer_config}

        if auctioneer_config is None:
            return None
        else:
            self.logger.info("Configuring auctioneer...")

        if ccu_store is None:
            self.logger.warning("No ccu_store configured")

        fleet = self._config_params.get('resources').get('fleet')
        if fleet is None:
            self.logger.error("No fleet found in config file, can't configure allocator")
            return

        auctioneer = Auctioneer(robot_ids=fleet, ccu_store=ccu_store, api=self._api, **auctioneer_config)

        return auctioneer

    def configure_robot_proxy(self, robot_id):
        allocation_config = self._config_params.get('plugins').get('task_allocation')
        robot_proxy_config = self._config_params.get('robot_proxy')

        if robot_proxy_config is None:
            return None
        self.logger.info("Configuring robot proxy %s...", robot_id)

        robot_store_config = self._config_params.get('robot_store')
        if robot_store_config is None:
            self.logger.warning("No robot_store configured")
            return None

        api_config = robot_proxy_config.get('api')
        api_config['zyre']['zyre_node']['node_name'] = robot_id + '_proxy'
        api = configure.configure_component('api', **api_config)

        db_name = robot_store_config.get('db_name') + '_' + robot_id
        robot_store_config.update(dict(db_name=db_name))
        robot_store = configure.configure_component('ccu_store', **robot_store_config)

        stp_solver = allocation_config.get('stp_solver')
        task_type = allocation_config.get('task_type')

        robot_config = {"robot_id": robot_id,
                               "api": api,
                               "robot_store": robot_store,
                               "stp_solver": stp_solver,
                               "task_type": task_type}

        bidder_config = robot_proxy_config.get('bidder')

        schedule_monitor_config = robot_proxy_config.get('schedule_monitor')

        robot_proxy = Robot(robot_config, bidder_config,
                            schedule_monitor_config=schedule_monitor_config)

        return robot_proxy




