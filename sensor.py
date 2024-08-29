"""
Home Assistant support for the TFA Dostmann: CO2 Monitor AIRCO2NTROL MINI sensor.

Date:     2018-12-04
Homepage: https://github.com/jansauer/home-assistant_config/tree/master/config/custom_components/airco2ntrol
Author:   Jan Sauer

Date:     2022-10-10
Modified: Leonhard Lerbs

Date:     2024-02-15
Modified: Pepijn de Vos
"""
import fcntl
import logging
import voluptuous as vol
from os import listdir

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorDeviceClass
from homeassistant.const import UnitOfTemperature, CONCENTRATION_PARTS_PER_MILLION, PERCENTAGE
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

DEFAULT_DEVICE = '/dev/hidraw0'

IDX_FNK = 0
IDX_MSB = 1
IDX_LSB = 2
IDX_CHK = 3

HIDIOCSFEATURE_9 = 0xC0094806

def getDevicePath():
    path_end = next((x for x in listdir('/dev/') if 'hidraw' in x), None)
    if path_end is None:
        raise IOError
    _LOGGER.debug("Trying device: " + '/dev/' + path_end)
    return '/dev/' + path_end

def setup_platform(hass, config, add_entities, discovery_info=None):
    _LOGGER.debug("Set up the AirCO2ntrol component.")
    state = AirCO2ntrolReader()
    add_entities([
      AirCO2ntrolCarbonDioxideSensor(state),
      AirCO2ntrolTemperatureSensor(state),
      AirCO2ntrolHumiditySensor(state)
    ])
    return True


class AirCO2ntrolReader:
    """A AirCO2ntrol sensor reader."""

    def __init__(self):
        """Initialize the reader."""
        self.carbonDioxide = None
        self.temperature = None
        self.humidity = None
        self._fp = None

    def update(self):
        _LOGGER.debug("Poll latest sensor data.")
        carbonDioxide = None
        temperature = None
        humidity = None

        for pollDeviceForCorrectData in range(10):
            _LOGGER.debug("Device " + str(pollDeviceForCorrectData))
            data = self.__save_poll()
            if data is None:
                break

            _LOGGER.debug("polled hex data = " + hexArrayToString(data))

            value = (data[IDX_MSB] << 8) | data[IDX_LSB]
            _LOGGER.debug('value is: ' + str(value))
            if data[0] == 0x50:
                carbonDioxide = value
            elif data[0] == 0x42:
                temperature = value / 16.0 - 273.15
            elif data[0] == 0x41:
                humidity = value / 100

            if carbonDioxide is not None and temperature is not None and humidity is not None:
                break

        self.temperature = temperature
        self.carbonDioxide = carbonDioxide
        self.humidity = humidity
        _LOGGER.debug('AirCO2ntrol measurement: temperature = ' + str(self.temperature)+ ', carbonDioxide = ' + str(self.carbonDioxide) + ', humidity = ' + str(self.humidity))



    def __save_poll(self):
        try:
            data = list(e for e in self._fp.read(5))
        except:
            try:
                self.__recover()
                data = list(e for e in self._fp.read(5))
            except:
                _LOGGER.warning('Connection to CO2 Sensor failed')
                return None

        if ((data[IDX_MSB] + data[IDX_LSB] + data[IDX_FNK]) % 256) != data[IDX_CHK]:
            _LOGGER.error('Checksum incorrect. Values:' + hexArrayToString(data))
            return None

        return data

    def __recover(self):
        _LOGGER.info("Trying recover()")
        self._fp = open(getDevicePath(), 'ab+', 0)
        fcntl.ioctl(self._fp, HIDIOCSFEATURE_9, bytearray.fromhex('00 c4 c6 c0 92 40 23 dc 96'))



def hexArrayToString(array):
    return '[' + ','.join('{:02x}'.format(x) for x in array) + ']'


class AirCO2ntrolCarbonDioxideSensor(Entity):
    """A AirCO2ntrol carbon dioxide sensor."""

    def __init__(self, state):
        """Initialize the sensor."""
        self._state = state

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'AirCO2ntrol Carbon Dioxide'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state.carbonDioxide

    @property
    def unit_of_measurement(self):
        """Return the units of measurement."""
        return CONCENTRATION_PARTS_PER_MILLION

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return SensorDeviceClass.CO2

    @property
    def icon(self):
        """Return the icon of device based on its type."""
        return 'mdi:molecule-co2'

    def update(self):
        """Get the latest data and updates the state."""
        _LOGGER.debug("Updating AirCO2ntrol for carbon dioxide")
        self._state.update()
      
class AirCO2ntrolTemperatureSensor(Entity):
    """A AirCO2ntrol temperature sensor."""

    def __init__(self, state):
        """Initialize the sensor."""
        self._state = state

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'AirCO2ntrol Temperature'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state.temperature

    @property
    def unit_of_measurement(self):
        """Return the units of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return SensorDeviceClass.TEMPERATURE

    @property
    def icon(self):
        """Return the icon of device based on its type."""
        return 'mdi:thermometer'

    def update(self):
        """Get the latest data and updates the state."""
        _LOGGER.debug("Updating AirCO2ntrol for temperature")
        self._state.update()

class AirCO2ntrolHumiditySensor(Entity):
    """A AirCO2ntrol humidity sensor."""

    def __init__(self, state):
        """Initialize the sensor."""
        self._state = state

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'AirCO2ntrol Humidity'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state.humidity

    @property
    def unit_of_measurement(self):
        """Return the units of measurement."""
        return PERCENTAGE

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return SensorDeviceClass.HUMIDITY

    @property
    def icon(self):
        """Return the icon of device based on its type."""
        return 'mdi:water-percent'

    def update(self):
        """Get the latest data and updates the state."""
        _LOGGER.debug("Updating AirCO2ntrol for temperature")
        self._state.update()
