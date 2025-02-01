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
from homeassistant.exceptions import ConfigEntryNotReady
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


def get_device_unique_id(file):
    """Get a unique ID for the HID device based on available attributes."""
    try:
        hid_uniq = None
        hid_id = None

        for line in file:
            if line.startswith("HID_UNIQ="):
                hid_uniq = line.strip().split("=")[1]
            elif line.startswith("HID_ID="):
                parts = line.strip().split("=")[1].split(":")
                if len(parts) >= 3:
                    hid_id = f"{parts[1]}:{parts[2]}"  # Extract VID:PID

        # Prefer HID_UNIQ if available
        if hid_uniq and hid_uniq != "":
            return hid_uniq
        elif hid_id:
            return hid_id

    except FileNotFoundError:
        _LOGGER.warning(f"Cannot read {file}. Cannot determine unique ID of device")
        raise


def get_device_path():
    """Find the correct HID device and return (device_path, unique_id)."""
    try:
        for device in os.listdir('/sys/class/hidraw/'):
            uevent_path = f"/sys/class/hidraw/{device}/device/uevent"

            try:
                with open(uevent_path, "r") as file:
                    for line in file:
                        if line.startswith("HID_NAME="):
                            device_name = line.strip().split("=")[1]
                            if any(keyword in device_name for keyword in HID_KEYWORDS):
                                unique_id = get_device_unique_id(file)
                                return f"/dev/{device}", unique_id

            except FileNotFoundError:
                _LOGGER.warning(f"Cannot read {uevent_path}, skipping.")

        raise FileNotFoundError("No matching HID device found.")

    except Exception as e:
        _LOGGER.error(f"Error finding HID device: {e}")
        raise

class AirCO2ntrolReader:
    """Class to interact with the AirCO2ntrol sensor."""

    def __init__(self):
        """Initialize the reader."""
        self.carbon_dioxide = None
        self.temperature = None
        self.humidity = None
        self._fp = None

    def _recover(self):
        """Attempt to recover the connection to the device."""
        try:
            self.device_path, _ = get_device_path()
            _LOGGER.info("Trying to initialize connection...")
            self._fp = open(self.device_path, 'ab+', 0)
            fcntl.ioctl(self._fp, HIDIOCSFEATURE_9, bytearray.fromhex('00 c4 c6 c0 92 40 23 dc 96'))
        except FileNotFoundError as e:
            _LOGGER.warning(f"Did not find HID device. Is it plugged in? Message: {e}")
            self._fp = None
        except Exception as e:
            _LOGGER.error(f"Device initialization failed: {e}")
            self._fp = None

    def update(self):
        """Poll the latest sensor data."""
        if not self._fp:
            _LOGGER.warning("Currently no devce connected. Trying to find and connect to CO2 Device.")
            self._recover()
            if not self._fp:
                return {
                    "co2": None,
                    "temperature": None,
                    "humidity": None,
                    "available": False
                }

        _LOGGER.debug("Polling latest sensor data.")
        got_carbon_dioxide = None
        got_temperature = None
        got_humidity = None
        for _ in range(5):  # Try a few times
            data = self._safe_poll()
            if data:
                value = (data[IDX_MSB] << 8) | data[IDX_LSB]
                if data[IDX_FNK] == 0x50:
                    if value > 10000:
                        # sometimes the first read of this value is something around 25k.
                        # This is a safety to filter such unplausible readings
                        continue
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
            # return all values, even if they are not the most recent
            "co2": self.carbon_dioxide,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "available": True
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

    try:
        _, unique_id = await hass.async_add_executor_job(get_device_path)
    except Exception as e:
        raise ConfigEntryNotReady(f"Could not setup device yet: {e}")

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
        AirCO2ntrolCarbonDioxideSensor(coordinator, unique_id),
        AirCO2ntrolTemperatureSensor(coordinator, unique_id),
        AirCO2ntrolHumiditySensor(coordinator, unique_id)
    ])


class AirCO2ntrolSensor(CoordinatorEntity, SensorEntity):
    """Base class for AirCO2ntrol sensors."""

    def __init__(self, coordinator, name, sensor_type, unit, icon, device_class, unique_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_unique_id = f"{unique_id}-{sensor_type}"
        self.sensor_type = sensor_type

    @property
    def native_value(self):
        """Return the current sensor state."""
        return self.coordinator.data.get(self.sensor_type)

    @property
    def available(self) -> bool:
        return self.coordinator.data.get("available")

class AirCO2ntrolCarbonDioxideSensor(AirCO2ntrolSensor):
    """CO2 Sensor."""

    def __init__(self, coordinator, unique_id):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Carbon Dioxide",
            sensor_type="co2",
            unit=CONCENTRATION_PARTS_PER_MILLION,
            icon="mdi:molecule-co2",
            device_class=SensorDeviceClass.CO2,
            unique_id=unique_id
        )


class AirCO2ntrolTemperatureSensor(AirCO2ntrolSensor):
    """Temperature Sensor."""

    def __init__(self, coordinator, unique_id):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Temperature",
            sensor_type="temperature",
            unit=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
            device_class=SensorDeviceClass.TEMPERATURE,
            unique_id=unique_id
        )


class AirCO2ntrolHumiditySensor(AirCO2ntrolSensor):
    """Humidity Sensor."""

    def __init__(self, coordinator, unique_id):
        super().__init__(
            coordinator,
            name="AirCO2ntrol Humidity",
            sensor_type="humidity",
            unit=PERCENTAGE,
            icon="mdi:water-percent",
            device_class=SensorDeviceClass.HUMIDITY,
            unique_id=unique_id
        )
