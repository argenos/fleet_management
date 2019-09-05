import logging

from importlib_resources import open_text
from mrs.robot import Robot
from ropod.utils.config import read_yaml_file, get_config
from ropod.utils.logging.config import config_logger

from fleet_management.exceptions.config import InvalidConfig

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


class ConfigParams(dict):

    def __init__(self, config_file=None):
        super().__init__()
        if config_file is None:
            config = _load_default_config()
        else:
            config = _load_file(config_file)

        self.update(**config)

    @classmethod
    def component(cls, component, config_file=None):
        config = cls(config_file)
        return config.pop(component)


def _load_default_config():
    config_file = open_text('fleet_management.config.default', 'config.yaml')
    config = get_config(config_file)
    return config


def _load_file(config_file):
    config = read_yaml_file(config_file)
    return config


default_config = ConfigParams()
default_logging_config = default_config.pop('logger')


class Configurator(object):

    def __init__(self, config_file=None, logger=True, **kwargs):
        self.logger = logging.getLogger('fms.config.configurator')
        self._builder = configure
        self._plugin_factory = plugin_factory

        self._components = dict()
        self._plugins = dict()

        self._config_params = ConfigParams(config_file)

        if logger:
            log_file = kwargs.get('log_file', None)
            self.configure_logger(filename=log_file)

    def configure(self):
        components = self._builder.configure(self._config_params)
        self._components.update(**components)
        plugins = self._configure_plugins(ccu_store=self._components.get('ccu_store'),
                                          api=self._components.get('api'))

        self._plugins.update(**plugins)
        for name, component in components.items():
            self.add_plugins(name)
            self.configure_components(name)

    def add_plugins(self, component_name):
        """Adds all the plugins specified in the config file to a component

        Args:
            component_name (str): The name of the component
        """
        component = self._components.get(component_name)
        component_config = self._config_params.get(component_name)
        self.logger.debug('Adding plugins to %s', component_name)
        if hasattr(component, 'add_plugin'):
            plugins = component_config.get('plugins', list())
            for plugin in plugins:
                self.add_plugin(component, plugin, attr_name=plugin)

    def add_plugin(self, component, plugin_name, attr_name=None):
        """ Adds one plugin to a component

        Args:
            component (object): The object instance to which the component should be added
            plugin_name (str): The plugin to add (should already be registered in
                                the plugins dictionary)
            attr_name (str): The name of the attribute of the plugin in the desired component
        """
        plugin = self._plugins.get(plugin_name)
        component.add_plugin(plugin, attr_name)

    def configure_components(self, component_name):
        """Use the configure interface of a component, if it has one

        Args:
            component_name (str): The name of the component
        """

        component = self._components.get(component_name)
        component_config = self._config_params.get(component_name)
        if hasattr(component, 'configure'):
            self.logger.debug('Configuring %s', component_name)
            component.configure(**component_config)

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
        return self.get_component('api')

    @property
    def ccu_store(self):
        return self.get_component('ccu_store')

    @property
    def task_manager(self):
        return self.get_component('task_manager')

    @property
    def resource_manager(self):
        return self.get_component('resource_manager')

    def get_component(self, component):
        if component in self._components.keys():
            return self._components.get(component)
        else:
            return self._create_component(component)

    def _create_component(self, name):
        component_config = self._config_params.get(name)
        component_ = self._builder.get_component(name, **component_config)
        self._components[name] = component_
        return component_

    def _configure_plugins(self, ccu_store, api):
        logging.info("Configuring FMS plugins...")
        plugin_config = self._config_params.get('plugins')
        if plugin_config is None:
            self.logger.debug("Found no plugins in the configuration file.")
            return None

        for plugin, config in plugin_config.items():
            try:
                component = self._plugin_factory.configure(plugin, ccu_store=ccu_store, api=api, **config)
            except ValueError:
                self.logger.error("No builder registered for %s", plugin)
                continue

            if isinstance(component, dict):
                self._plugins.update(**component)
            else:
                self._plugins[plugin] = component

        return self._plugins

    def configure_robot_proxy(self, robot_id):
        allocation_config = self._config_params.get('plugins').get('mrta')
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



