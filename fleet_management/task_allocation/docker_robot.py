from __future__ import print_function
from fleet_management.config.config_file_reader import ConfigFileReader
from fleet_management.task_allocation import Robot
from fleet_management.db.ccu_store import CCUStore
import time

import argparse

if __name__ == '__main__':

    config_params = ConfigFileReader.load("../../config/ccu_config.yaml")
    ccu_store = CCUStore(config_params.ccu_store_db_name)

    parser = argparse.ArgumentParser()
    parser.add_argument('ropod_id', type=str, help='example: ropod_001')
    args = parser.parse_args()
    ropod_id = args.ropod_id

    time.sleep(5)

    robot = Robot(ropod_id, config_params, ccu_store, verbose_mrta=True)

    try:
        while True:
            time.sleep(0.5)
        raise KeyboardInterrupt
    except (KeyboardInterrupt, SystemExit):
        print("Terminating mock robot...")
        robot.shutdown()
        print("Exiting...")
