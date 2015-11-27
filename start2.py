#!/usr/bin/env python
import sys
sys.path.insert(0, 'lib')
from m2ee import logger
from start import *
import logging

logger.setLevel(logging.INFO)

logger.info('Starting Mendix Application')

if __name__ == '__main__':
    pre_process_m2ee_yaml()
    activate_license()
    set_up_logging_file()
    m2ee = set_up_m2ee_client(get_vcap_data())

    def sigterm_handler(_signo, _stack_frame):
        m2ee.stop()
        loop_until_process_dies(m2ee, 1)

    signal.signal(signal.SIGTERM, sigterm_handler)

    start_app(m2ee)
    create_admin_user(m2ee)
    display_running_version(m2ee)
    configure_debugger(m2ee)
    loop_until_process_dies(m2ee)
