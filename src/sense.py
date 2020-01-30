#!/usr/bin/env python3

#
# import dependencies
#
import time
import json
import signal
from threading import Event
import RPi.GPIO as GPIO

import utils
from configs import Configs
from mqtt import MqttHelper
from gpio import GpioHelper

class App:
    def __init__(self, error_handler):
        # initilize running variable for tracking quit state
        self.exit = False

        self.error_handler = error_handler

        # load configuration
        self.config = Configs.load('/src/configuration.yaml')

        # setup GPIO pins
        self.gpio = GpioHelper(self.config.sensors)

        # setup mqtt client, then
        # initialize mqtt connection & begin loop
        self.mqtt = MqttHelper(
                self.config.mqtt_host,
                self.config.mqtt_port).connect()

        self.fault_signal("FAILED")

    def motion(self, pin_returned):
        sensor = self.config.sensors[pin_returned]
        topic = self.config.root_topic + sensor['group'] + '/' + sensor['type'] + '/' + sensor['name']
        state = "ALARM" if self.gpio.is_rising(pin_returned) else "OK"

        utils.log(
            "{state} on pin {pin_returned}, "
            "sending mqtt event to {topic}"
            .format(
                state=state,
                pin_returned=pin_returned,
                topic=topic
            )
        )

        res = {
            'state': state,
            'sensor_data': sensor,
            'timestamp': utils.timestamp(),
        }

        self.mqtt.publish(topic, json.dumps(res), retain=True)

    def fault_signal(self, fault_state):
        if fault_state == "FAILED" or fault_state == "OK":
            state = fault_state
        else:
            raise ValueError("'{fault_state}' is not a valid input for `fault_signal()`")

        topic = self.config.root_topic + "fault"
        res = {
            'id': 'fault',
            'state': state,
            'timestamp': utils.timestamp(),
        }

        utils.log(
            "fault state set to {state}, "
            "sending mqtt event to {topic}"
            .format(
                state=state,
                topic=topic,
            )
        )

        self.mqtt.publish(topic, json.dumps(res), retain=True)

    def run(self):
        def cb(pin_returned):
            # wrap callback in a try/except that rethrows errors to the main thread
            # so that the app doesn't keep chugging along thinking everything is okay
            try:
                return self.motion(pin_returned)
            except Exception as e:
                self.error_handler(e, self.quit)

        self.gpio.start_listening(cb)

        while not self.exit:
            self.fault_signal("OK")
            time.sleep(600)


    def quit(self):
        self.exit = True

        # cleanup
        self.fault_signal("FAILED")
        self.gpio.stop_listening()
        self.mqtt.disconnect()
        utils.log("rpi-pir2mqtt successfully shut down")

def error_handler(exception, cb):
    utils.log("An unexpected error has occurred, exiting app...")
    cb()
    raise exception

def sig_handler(signo, _frame):
    utils.log("sig_handler processing quit signal")
    APP.quit()

APP = App(error_handler)
signal.signal(signal.SIGTERM, sig_handler)
signal.signal(signal.SIGINT, sig_handler)

try:
    utils.log("Starting app...")
    APP.run()
except SystemExit:
    utils.log("SystemExit caught, quitting...")
    APP.quit()
except Exception as e:
    error_handler(e, APP.quit())