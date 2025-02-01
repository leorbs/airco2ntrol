"""
Home Assistant support for the TFA Dostmann: CO2 Monitor AIRCO2NTROL MINI sensor.

Original Implementation:
Homepage: https://github.com/jansauer/home-assistant_config/tree/master/config/custom_components/airco2ntrol
"""
import fcntl
import logging
import os
import datetime

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature, CONCENTRATION_PARTS_PER_MILLION, PERCENTAGE
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

HIDIOCSFEATURE_9 = 0xC0094806


POLL_INTERVAL = 10  # seconds
POLL_INTERVAL_TIMEDELTA = datetime.timedelta(seconds=POLL_INTERVAL)

IDX_FNK = 0
IDX_MSB = 1
IDX_LSB = 2
IDX_CHK = 3


HID_KEYWORDS = ["Holtek", "zyTemp"]  # Adjust based on your actual device name


def get_device_path():
    """Find the correct HID device by reading its HID_NAME from sysfs."""
    try:
        for device in os.listdir('/sys/class/hidraw/'):
            uevent_path = f"/sys/class/hidraw/{device}/device/uevent"

            try:
                with open(uevent_path, "r") as file:
                    for line in file:
                        if line.startswith("HID_NAME="):
                            device_name = line.strip().split("=")[1]
                            _LOGGER.debug(f"Found HID device: {device_name} at {device}")

                            # Check if the device matches the expected keywords
                            if any(keyword in device_name for keyword in HID_KEYWORDS):
                                _LOGGER.info(f"Using device: {device_name} -> /dev/{device}")
                                return f"/dev/{device}"

            except FileNotFoundError:
                _LOGGER.warning(f"Cannot read {uevent_path}, skipping.")

        raise FileNotFoundError("No matching HID device found. Valid keywords for HID_NAME are " + str(HID_KEYWORDS))

    except Exception as e:
        _LOGGER.error(f"Error finding HID device: {e}")
        return None

class DeviceNotFoundException(Exception):
    pass

class AirCO2ntrolReader:
    """Class to interact with the AirCO2ntrol sensor."""

    def __init__(self):
        """Initialize the reader."""
        self.carbon_dioxide = None
        self.temperature = None
        self.humidity = None
        self._fp = None
        # initial connection
        self._recover()

    def _recover(self):
        """Attempt to recover the connection to the device."""
        try:
            self.device_path = get_device_path()
            if not self.device_path:
                raise DeviceNotFoundException("could not find device")
            _LOGGER.info("Trying to recover connection...")
            self._fp = open(self.device_path, 'ab+', 0)
            fcntl.ioctl(self._fp, HIDIOCSFEATURE_9, bytearray.fromhex('00 c4 c6 c0 92 40 23 dc 96'))
        except DeviceNotFoundException as e:
            _LOGGER.warning(f"{e}")
            self._fp = None
        except Exception as e:
            _LOGGER.error(f"Device initialization failed: {e}")
            self._fp = None

    def update(self):
        """Poll the latest sensor data."""
        if not self._fp:
            _LOGGER.warning("No connected device found. Trying to find connected devices:")
            self._recover()
            return None

        _LOGGER.debug("Polling latest sensor data.")
        got_carbon_dioxide = None
        got_temperature = None
        got_humidity = None
        for _ in range(5):  # Try a few times
            data = self._safe_poll()
            if data:
                value = (data[IDX_MSB] << 8) | data[IDX_LSB]
                if data[IDX_FNK] == 0x50:
                    self.carbon_dioxide = value
                    got_carbon_dioxide = True
                elif data[IDX_FNK] == 0x42:
                    self.temperature = value / 16.0 - 273.15
                    got_temperature = True
                elif data[IDX_FNK] == 0x41:
                    self.humidity = value / 100
                    got_humidity = True

                if got_carbon_dioxide and got_temperature and got_humidity:
                    break  # We got all values
        return {
            # return all values, even if they are the most recent
            "co2": self.carbon_dioxide,
            "temperature": self.temperature,
            "humidity": self.humidity
        }

    def _safe_poll(self):
        """Safely read from the device."""
        try:
            data = list(self._fp.read(5))
            if ((data[IDX_MSB] + data[IDX_LSB] + data[IDX_FNK]) % 256) != data[IDX_CHK]:
                _LOGGER.error("Checksum incorrect: %s", data)
                return None
            return data
        except Exception as e:
            _LOGGER.warning(f"Error reading sensor data. Resetting device connection: {e}")
            self._fp = None
            return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up sensors from a config entry using the new DataUpdateCoordinator."""

    reader = AirCO2ntrolReader()

    async def async_update():
        """Fetch data asynchronously."""
        return await hass.async_add_executor_job(reader.update)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="AirCO2ntrol",
        update_method=async_update,
        update_interval=POLL_INTERVAL_TIMEDELTA
    )

    await coordinator.async_config_entry_first_refresh()

    async_add_entities([
        AirCO2ntrolCarbonDioxideSensor(coordinator),
        AirCO2ntrolTemperatureSensor(coordinator),
        AirCO2ntrolHumiditySensor(coordinator)
    ])


class AirCO2ntrolSensor(CoordinatorEntity, SensorEntity):
    """Base class for AirCO2ntrol sensors."""

    def __init__(self, coordinator, name, sensor_type, unit, icon, device_class):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        self.sensor_type = sensor_type

    @property
    def native_value(self):
        """Return the current sensor state."""
        return self.coordinator.data.get(self.sensor_type)


class AirCO2ntrolCarbonDioxideSensor(AirCO2ntrolSensor):
    """CO2 Sensor."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Carbon Dioxide",
            sensor_type="co2",
            unit=CONCENTRATION_PARTS_PER_MILLION,
            icon="mdi:molecule-co2",
            device_class=SensorDeviceClass.CO2
        )


class AirCO2ntrolTemperatureSensor(AirCO2ntrolSensor):
    """Temperature Sensor."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Temperature",
            sensor_type="temperature",
            unit=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
            device_class=SensorDeviceClass.TEMPERATURE
        )


class AirCO2ntrolHumiditySensor(AirCO2ntrolSensor):
    """Humidity Sensor."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Humidity",
            sensor_type="humidity",
            unit=PERCENTAGE,
            icon="mdi:water-percent",
            device_class=SensorDeviceClass.HUMIDITY
        )
