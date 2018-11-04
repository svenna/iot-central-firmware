# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. 

import os
import logging
import logging.config
import logging.handlers


logToConsole = False

def init():
    logger = logging.getLogger("iotcentral")
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    logger.addHandler(handler)

    logger.debug("SysLogHandler setup")


def getLogger():
    return logging.getLogger("iotcentral")
# def log(message):
#     global logFile

#     # check if need to truncate
#     if os.stat('../device.log').st_size >= 104857600:
#         logFile.truncate(419430400)
#     if logToConsole:
#         print(message)
#     else:
#         logFile.write(message + "\n")
#         logFile.flush()
