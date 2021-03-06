"""
homeassistant.components.sensor.zwave
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Interfaces with Z-Wave sensors.

For more details about this platform, please refer to the documentation
at https://home-assistant.io/components/zwave/
"""
# Because we do not compile openzwave on CI
# pylint: disable=import-error
import datetime

from homeassistant.helpers.event import track_point_in_time
import homeassistant.util.dt as dt_util
import homeassistant.components.zwave as zwave
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
    ATTR_BATTERY_LEVEL, STATE_ON, STATE_OFF,
    TEMP_CELCIUS, TEMP_FAHRENHEIT, ATTR_LOCATION)

PHILIO = '013c'
PHILIO_SLIM_SENSOR = '0002'
PHILIO_SLIM_SENSOR_MOTION = (PHILIO, PHILIO_SLIM_SENSOR, 0)

WORKAROUND_NO_OFF_EVENT = 'trigger_no_off_event'

DEVICE_MAPPINGS = {
    PHILIO_SLIM_SENSOR_MOTION: WORKAROUND_NO_OFF_EVENT,
}


def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Sets up Z-Wave sensors. """

    # Return on empty `discovery_info`. Given you configure HA with:
    #
    # sensor:
    #   platform: zwave
    #
    # `setup_platform` will be called without `discovery_info`.
    if discovery_info is None:
        return

    node = zwave.NETWORK.nodes[discovery_info[zwave.ATTR_NODE_ID]]
    value = node.values[discovery_info[zwave.ATTR_VALUE_ID]]

    value.set_change_verified(False)

    # if 1 in groups and (zwave.NETWORK.controller.node_id not in
    #                     groups[1].associations):
    #     node.groups[1].add_association(zwave.NETWORK.controller.node_id)

    specific_sensor_key = (value.node.manufacturer_id,
                           value.node.product_id,
                           value.index)

    # Check workaround mappings for specific devices
    if specific_sensor_key in DEVICE_MAPPINGS:
        if DEVICE_MAPPINGS[specific_sensor_key] == WORKAROUND_NO_OFF_EVENT:
            # Default the multiplier to 4
            re_arm_multiplier = (zwave.get_config_value(value.node, 9) or 4)
            add_devices([
                ZWaveTriggerSensor(value, hass, re_arm_multiplier * 8)
            ])

    # generic Device mappings
    elif value.command_class == zwave.COMMAND_CLASS_SENSOR_BINARY:
        add_devices([ZWaveBinarySensor(value)])

    elif value.command_class == zwave.COMMAND_CLASS_SENSOR_MULTILEVEL:
        add_devices([ZWaveMultilevelSensor(value)])

    elif (value.command_class == zwave.COMMAND_CLASS_METER and
          value.type == zwave.TYPE_DECIMAL):
        add_devices([ZWaveMultilevelSensor(value)])

    elif value.command_class == zwave.COMMAND_CLASS_ALARM:
        add_devices([ZWaveAlarmSensor(value)])


class ZWaveSensor(Entity):
    """ Represents a Z-Wave sensor. """

    def __init__(self, sensor_value):
        from openzwave.network import ZWaveNetwork
        from pydispatch import dispatcher

        self._value = sensor_value
        self._node = sensor_value.node

        dispatcher.connect(
            self.value_changed, ZWaveNetwork.SIGNAL_VALUE_CHANGED)

    @property
    def should_poll(self):
        """ False because we will push our own state to HA when changed. """
        return False

    @property
    def unique_id(self):
        """ Returns a unique id. """
        return "ZWAVE-{}-{}".format(self._node.node_id, self._value.object_id)

    @property
    def name(self):
        """ Returns the name of the device. """
        name = self._node.name or "{} {}".format(
            self._node.manufacturer_name, self._node.product_name)

        return "{} {}".format(name, self._value.label)

    @property
    def state(self):
        """ Returns the state of the sensor. """
        return self._value.data

    @property
    def state_attributes(self):
        """ Returns the state attributes. """
        attrs = {
            zwave.ATTR_NODE_ID: self._node.node_id,
        }

        battery_level = self._node.get_battery_level()

        if battery_level is not None:
            attrs[ATTR_BATTERY_LEVEL] = battery_level

        location = self._node.location

        if location:
            attrs[ATTR_LOCATION] = location

        return attrs

    @property
    def unit_of_measurement(self):
        return self._value.units

    def value_changed(self, value):
        """ Called when a value has changed on the network. """
        if self._value.value_id == value.value_id:
            self.update_ha_state()


# pylint: disable=too-few-public-methods
class ZWaveBinarySensor(ZWaveSensor):
    """ Represents a binary sensor within Z-Wave. """

    @property
    def state(self):
        """ Returns the state of the sensor. """
        return STATE_ON if self._value.data else STATE_OFF


class ZWaveTriggerSensor(ZWaveSensor):
    """
    Represents a stateless sensor which
    triggers events just 'On' within Z-Wave.
    """

    def __init__(self, sensor_value, hass, re_arm_sec=60):
        """
        :param sensor_value: The z-wave node
        :param hass:
        :param re_arm_sec: Set state to Off re_arm_sec after the last On event
        :return:
        """
        super(ZWaveTriggerSensor, self).__init__(sensor_value)
        self._hass = hass
        self.invalidate_after = dt_util.utcnow()
        self.re_arm_sec = re_arm_sec

    def value_changed(self, value):
        """ Called when a value has changed on the network. """
        if self._value.value_id == value.value_id:
            self.update_ha_state()
            if value.data:
                # only allow this value to be true for 60 secs
                self.invalidate_after = dt_util.utcnow() + datetime.timedelta(
                    seconds=self.re_arm_sec)
                track_point_in_time(
                    self._hass, self.update_ha_state,
                    self.invalidate_after)

    @property
    def state(self):
        """ Returns the state of the sensor. """
        if not self._value.data or \
                (self.invalidate_after is not None and
                 self.invalidate_after <= dt_util.utcnow()):
            return STATE_OFF

        return STATE_ON


class ZWaveMultilevelSensor(ZWaveSensor):
    """ Represents a multi level sensor Z-Wave sensor. """

    @property
    def state(self):
        """ Returns the state of the sensor. """
        value = self._value.data

        if self._value.units in ('C', 'F'):
            return round(value, 1)
        elif isinstance(value, float):
            return round(value, 2)

        return value

    @property
    def unit_of_measurement(self):
        unit = self._value.units

        if unit == 'C':
            return TEMP_CELCIUS
        elif unit == 'F':
            return TEMP_FAHRENHEIT
        else:
            return unit


class ZWaveAlarmSensor(ZWaveSensor):
    """ A Z-wave sensor that sends Alarm alerts

    Examples include certain Multisensors that have motion and
    vibration capabilities. Z-Wave defines various alarm types
    such as Smoke, Flood, Burglar, CarbonMonoxide, etc.

    This wraps these alarms and allows you to use them to
    trigger things, etc.

    COMMAND_CLASS_ALARM is what we get here.
    """
    # Empty subclass for now. Allows for later customizations
    pass
