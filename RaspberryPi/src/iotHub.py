# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license.

from datetime import datetime
import json
import iothub_client
from iothub_client import IoTHubClient, IoTHubClientError, IoTHubTransportProvider, IoTHubClientResult
from iothub_client import IoTHubMessage, IoTHubMessageDispositionResult, IoTHubError, DeviceMethodReturnValue
from iothub_client import IoTHubClientRetryPolicy, GetRetryPolicyReturnValue, IoTHubSecurityType
import deviceState
import logger
from collections import OrderedDict

class IotHubClient:

    MESSAGE_TIMEOUT = 10000
    RECEIVE_CONTEXT = 0
    TWIN_CONTEXT = 0
    METHOD_CONTEXT = 0
    CONNECTION_STATUS_CONTEXT = 0

    def __init__(self, iothub_uri, device_id, is_sas):
        self.methodCallbackList = {}
        self.desiredCallbackList = {}
        self.iothub_uri = iothub_uri
        self.device_id = device_id

        if is_sas:
            self.security_type = IoTHubSecurityType.SAS
        else:
            self.security_type = IoTHubSecurityType.X509

        self.protocol = IoTHubTransportProvider.MQTT
        self.methodCallbackCount = 0
        self.connectionCallbackCount = 0
        self.sendCallbackCount = 0
        self.sendReportedStateCallbackCount = 0
        try:
            self.client = self.iothub_client_init()

        except IoTHubError as iothub_error:
            log = logger.getLogger()
            log.error("Unexpected error {0} from IoTHub\n".format(iothub_error))
            return


    def iothub_client_init(self):
        log = logger.getLogger()
        # prepare iothub client
        log.debug("- creating the client with {0} {1} {2} {3}".format(self.iothub_uri, self.device_id, self.security_type.name, self.protocol.name))
        client = IoTHubClient(self.iothub_uri, self.device_id, self.security_type, self.protocol)

        # set the time until a message times out
        client.set_option("messageTimeout", self.MESSAGE_TIMEOUT)

        client.set_option("logtrace", 0)
        client.set_message_callback(self.receive_message_callback, self.RECEIVE_CONTEXT)
        client.set_device_twin_callback(self.device_twin_callback, self.TWIN_CONTEXT)
        client.set_device_method_callback(self.device_method_callback, self.METHOD_CONTEXT)
        client.set_connection_status_callback(self.connection_status_callback, self.CONNECTION_STATUS_CONTEXT)

        retryPolicy = IoTHubClientRetryPolicy.RETRY_INTERVAL
        retryInterval = 100
        client.set_retry_policy(retryPolicy, retryInterval)
        log.info("SetRetryPolicy to: retryPolicy = {0}".format(retryPolicy))
        log.info("SetRetryPolicy to: retryTimeoutLimitInSeconds = {0}".format(retryInterval))
        retryPolicyReturn = client.get_retry_policy()
        log.info("GetRetryPolicy returned: retryPolicy = {0}".format(retryPolicyReturn.retryPolicy))
        log.info("GetRetryPolicy returned: retryTimeoutLimitInSeconds = {0}\n".format(retryPolicyReturn.retryTimeoutLimitInSeconds))

        return client


    def registerMethod(self, methodName, callback):
        self.methodCallbackList[methodName.upper()] = callback


    def registerDesiredProperty(self, propertyName, callback):
        self.desiredCallbackList[propertyName.upper()] = callback


    def connection_status_callback(self, result, reason, user_context):
        log = logger.getLogger()
        log.info("Connection status changed[{0}] with:".format(user_context))
        log.info("    reason: {0}".format(reason))
        log.info("    result: {0}".format(result))
        self.connectionCallbackCount += 1
        log.info("    Total calls confirmed: {0}\n".format(self.connectionCallbackCount))


    def receive_message_callback(self, message, counter):
        log = logger.getLogger()
        message_buffer = message.get_bytearray()
        size = len(message_buffer)
        log.info("Received Message [{0}]:".format(counter))
        log.info("    Data: <<<{0}>>> & Size={1}".format(message_buffer[:size].decode('utf-8'), size))
        map_properties = message.properties()
        key_value_pair = map_properties.get_internals()
        log.info("    Properties: {0}".format(key_value_pair))
        deviceState.incC2dCount()
        log.info("    Total calls received: {0}\n".format(deviceState.getC2dCount()))

        # message format expected:
        # {
        #     "methodName" : "<method name>",
        #     "payload" : {
        #         "input1": "someInput",
        #         "input2": "anotherInput"
        #         ...
        #     }
        # }

        # lookup if the method has been registered to a function
        messageBody = json.loads(message_buffer[:size].decode('utf-8'))
        if messageBody["methodName"].upper() in self.methodCallbackList:
            self.methodCallbackList[messageBody["methodName"].upper()](messageBody["payload"])

        return IoTHubMessageDispositionResult.ACCEPTED


    def send_reported_state_callback(self, status_code, user_context):
        log = logger.getLogger()
        log.info("Confirmation[{0}] for reported state received with:".format(user_context))
        log.info("    status_code: {0}".format(status_code))
        self.sendReportedStateCallbackCount += 1
        log.info("    Total calls confirmed: {0}".format(self.sendReportedStateCallbackCount))


    def echoBackReported(self, propertyName, payload, status):
        value = payload[propertyName]["value"]
        if type(value) is bool:
            if value:
                value = "true"
            else:
                value = "false"
        reportedPayload = "{{\"{0}\":{{\"value\":{1}, \"statusCode\":{2}, \"status\": \"{3}\", \"desiredVersion\":{4}}}}}".format(propertyName, value, status[0], status[1], payload["$version"])
        self.send_reported_property(reportedPayload)


    def device_twin_callback(self, update_state, payload, user_context):
        log = logger.getLogger()
        log.info("Twin callback called with:")
        log.info("updateStatus: {0}".format(update_state))
        log.info("context: {0}".format(user_context))
        log.info("payload: {0}".format(payload))
        deviceState.incDesiredCount()
        log.info("Total calls confirmed: {0}\n".format(deviceState.getDirectCount()))

        # twin patch received
        if update_state == iothub_client.IoTHubTwinUpdateState.PARTIAL:
            params = json.loads(payload, object_pairs_hook=OrderedDict)
            propertyName = list(params)[0]
            if propertyName.upper() in self.desiredCallbackList:
                status = self.desiredCallbackList[propertyName.upper()](params[propertyName])
                self.echoBackReported(propertyName, params, status)
            deviceState.patchLastTwin(payload, True)

        # full twin update received
        elif update_state == iothub_client.IoTHubTwinUpdateState.COMPLETE:
            complete = json.loads(payload, object_pairs_hook=OrderedDict)
            for desired in complete["desired"]:
                if desired != "$version" and desired in complete["reported"]:
                    if complete["desired"]["$version"] != complete["reported"][desired]["desiredVersion"]:
                        if complete["reported"][desired]["value"] != complete["desired"][desired]["value"]:
                            if desired.upper() in self.desiredCallbackList:
                                status = self.desiredCallbackList[desired.upper()](complete["desired"][desired])
                                self.echoBackReported(desired, complete["desired"], status)
                        else:
                            status = (200, "completed")
                            self.echoBackReported(desired, complete["desired"], status)

            deviceState.setLastTwin(payload)


    def device_method_callback(self, method_name, payload, user_context):
        log = logger.getLogger()
        log.info("\nMethod callback called with:\nmethodName = {0}\npayload = {1}\ncontext = {2}".format(method_name, payload, user_context))
        deviceState.incDirectCount()
        log.info("Total calls confirmed: {0}".format(deviceState.getDirectCount()))

        # message format expected:
        # {
        #     "methodName": "reboot",
        #     "responseTimeoutInSeconds": 200,
        #     "payload": {
        #         "input1": "someInput",
        #         "input2": "anotherInput"
        #         ...
        #     }
        # }

        # lookup if the method has been registered to a function
        response = None
        if method_name.upper() in self.methodCallbackList:
            params = json.loads(payload)
            response = self.methodCallbackList[method_name.upper()](params)

        device_method_return_value = DeviceMethodReturnValue()
        device_method_return_value.response = "{ \"Response\": \"" + response[1] + "\" }"
        device_method_return_value.status = response[0]
        return device_method_return_value


    def send_confirmation_callback(self, message, result, user_context):
        log = logger.getLogger()
        log.info("Confirmation[{0}] received for message with result = {1}".format(user_context, result))
        map_properties = message.properties()
        log.info("    message_id: {0}".format(message.message_id))
        log.info("    correlation_id: {0}".format(message.correlation_id))
        key_value_pair = map_properties.get_internals()
        log.info("    Properties: {0}".format(key_value_pair))
        self.sendCallbackCount += 1
        log.info("    Total calls confirmed: {0}\n".format(self.sendCallbackCount))


    def send_message(self, payload):
        message = IoTHubMessage(bytearray(payload, 'utf8'))

        # add a timestamp property
        prop_map = message.properties()
        prop_map.add("timestamp", str(datetime.now()))

        deviceState.setLastSend(datetime.now())
        deviceState.setLastPayload(payload)

        self.client.send_event_async(message, self.send_confirmation_callback, deviceState.getSentCount())
        deviceState.incSentCount()


    def send_reported_property(self, reportedPayload):
        self.client.send_reported_state(reportedPayload, len(reportedPayload), self.send_reported_state_callback, deviceState.getReportedCount())
        deviceState.incReportedCount()
        deviceState.patchLastTwin(reportedPayload, False)
        