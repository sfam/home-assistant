"""
homeassistant.components.switch.wemo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Support for WeMo switches.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/switch.wemo/
"""
import logging

from homeassistant.components.switch import SwitchDevice
from homeassistant.const import (
    STATE_ON, STATE_OFF, STATE_STANDBY, EVENT_HOMEASSISTANT_STOP)

REQUIREMENTS = ['pywemo==0.3.8']
_LOGGER = logging.getLogger(__name__)

_WEMO_SUBSCRIPTION_REGISTRY = None


# pylint: disable=unused-argument, too-many-function-args
def setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """ Find and return WeMo switches. """
    import pywemo
    import pywemo.discovery as discovery

    global _WEMO_SUBSCRIPTION_REGISTRY
    if _WEMO_SUBSCRIPTION_REGISTRY is None:
        _WEMO_SUBSCRIPTION_REGISTRY = pywemo.SubscriptionRegistry()
        _WEMO_SUBSCRIPTION_REGISTRY.start()

        def stop_wemo(event):
            """ Shutdown Wemo subscriptions and subscription thread on exit"""
            _LOGGER.info("Shutting down subscriptions.")
            _WEMO_SUBSCRIPTION_REGISTRY.stop()

        hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, stop_wemo)

    if discovery_info is not None:
        location = discovery_info[2]
        mac = discovery_info[3]
        device = discovery.device_from_description(location, mac)

        if device:
            add_devices_callback([WemoSwitch(device)])

        return

    _LOGGER.info("Scanning for WeMo devices.")
    switches = pywemo.discover_devices()

    # Filter out the switches and wrap in WemoSwitch object
    add_devices_callback(
        [WemoSwitch(switch) for switch in switches
         if isinstance(switch, pywemo.Switch)])


class WemoSwitch(SwitchDevice):
    """ Represents a WeMo switch. """
    def __init__(self, wemo):
        self.wemo = wemo
        self.insight_params = None
        self.maker_params = None

        _WEMO_SUBSCRIPTION_REGISTRY.register(wemo)
        _WEMO_SUBSCRIPTION_REGISTRY.on(
            wemo, None, self._update_callback)

    def _update_callback(self, _device, _params):
        """ Called by the wemo device callback to update state. """
        _LOGGER.info(
            'Subscription update for  %s',
            _device)
        self.update_ha_state(True)

    @property
    def should_poll(self):
        """ No polling needed with subscriptions """
        return False

    @property
    def unique_id(self):
        """ Returns the id of this WeMo switch """
        return "{}.{}".format(self.__class__, self.wemo.serialnumber)

    @property
    def name(self):
        """ Returns the name of the switch if any. """
        return self.wemo.name

    @property
    def state(self):
        """ Returns the state. """
        is_on = self.is_on
        if not is_on:
            return STATE_OFF
        elif self.is_standby:
            return STATE_STANDBY
        return STATE_ON

    @property
    def current_power_mwh(self):
        """ Current power usage in mwh. """
        if self.insight_params:
            return self.insight_params['currentpower']

    @property
    def today_power_mw(self):
        """ Today total power usage in mw. """
        if self.insight_params:
            return self.insight_params['todaymw']

    @property
    def is_standby(self):
        """ Is the device on - or in standby. """
        if self.insight_params:
            standby_state = self.insight_params['state']
            # Standby  is actually '8' but seems more defensive
            # to check for the On and Off states
            if standby_state == '1' or standby_state == '0':
                return False
            else:
                return True

    @property
    def sensor_state(self):
        """ Is the sensor on or off. """
        if self.maker_params and self.has_sensor:
            # Note a state of 1 matches the WeMo app 'not triggered'!
            if self.maker_params['sensorstate']:
                return STATE_OFF
            else:
                return STATE_ON

    @property
    def switch_mode(self):
        """ Is the switch configured as toggle(0) or momentary (1). """
        if self.maker_params:
            return self.maker_params['switchmode']

    @property
    def has_sensor(self):
        """ Is the sensor present? """
        if self.maker_params:
            return self.maker_params['hassensor']

    @property
    def is_on(self):
        """ True if switch is on. """
        return self.wemo.get_state()

    def turn_on(self, **kwargs):
        """ Turns the switch on. """
        self.wemo.on()

    def turn_off(self):
        """ Turns the switch off. """
        self.wemo.off()

    def update(self):
        """ Update WeMo state. """
        try:
            self.wemo.get_state(True)
            if self.wemo.model_name == 'Insight':
                self.insight_params = self.wemo.insight_params
                self.insight_params['standby_state'] = (
                    self.wemo.get_standby_state)
            elif self.wemo.model_name == 'Maker':
                self.maker_params = self.wemo.maker_params
        except AttributeError:
            _LOGGER.warning('Could not update status for %s', self.name)
