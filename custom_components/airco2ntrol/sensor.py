"""
Home Assistant support for the TFA Dostmann: CO2 Monitor AIRCO2NTROL MINI sensor.

Original Implementation:
Homepage: https://github.com/jansauer/home-assistant_config/tree/master/config/custom_components/airco2ntrol
"""
import fcntl
import logging
import os
import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature, CONCENTRATION_PARTS_PER_MILLION, PERCENTAGE
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .sensor_reader import SensorReader
from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

HIDIOCSFEATURE_9 = 0xC0094806


POLL_INTERVAL = 20  # seconds
POLL_INTERVAL_TIMEDELTA = datetime.timedelta(seconds=POLL_INTERVAL)


CONVERGENCE_SPEED = 20

HID_KEYWORDS = ["Holtek", "zyTemp"]  # Adjust based on your actual device name


def get_device_path():
    """Find the correct HID device and return (device_path, unique_id)."""
    try:
        for device in os.listdir('/sys/class/hidraw/'):
            uevent_path = "/sys/class/hidraw/%s/device/uevent" % device

            try:
                with open(uevent_path, "r") as file:
                    lines = file.readlines()

                hid_name = None
                hid_uniq = None
                hid_id = None

                for line in lines:
                    if line.startswith("HID_NAME="):
                        hid_name = line.strip().split("=", 1)[1]
                    elif line.startswith("HID_UNIQ="):
                        hid_uniq = line.strip().split("=", 1)[1]
                    elif line.startswith("HID_ID="):
                        parts = line.strip().split("=", 1)[1].split(":")
                        if len(parts) >= 3:
                            hid_id = "%s:%s" % (parts[1], parts[2])

                if hid_name and any(keyword in hid_name for keyword in HID_KEYWORDS):
                    unique_id = None
                    if hid_uniq and hid_uniq != "":
                        unique_id = hid_uniq
                    elif hid_id:
                        unique_id = hid_id

                    if unique_id is None:
                        _LOGGER.warning(
                            "Found device %s but could not determine unique ID", device
                        )

                    return "/dev/%s" % device, unique_id

            except FileNotFoundError:
                _LOGGER.warning("Cannot read %s, skipping.", uevent_path)

        raise FileNotFoundError("No matching HID device found.")

    except FileNotFoundError:
        raise
    except Exception as e:
        _LOGGER.error("Error finding HID device: %s", e)
        raise


class AirCO2ntrolReader:
    """Class to interact with the AirCO2ntrol sensor."""

    def __init__(self, device_path=None):
        """Initialize the reader."""
        self.device_path = device_path
        self.carbon_dioxide = None
        self.temperature = None
        self.humidity = None
        self._sensor_reader = None

    def close(self):
        """Close the underlying device connection."""
        if self._sensor_reader is not None:
            self._sensor_reader.close()
            self._sensor_reader = None

    def _recover(self):
        """Attempt to recover the connection to the device."""
        self.close()
        fp = None
        try:
            if self.device_path:
                device_path = self.device_path
            else:
                device_path, _ = get_device_path()
            _LOGGER.info("Trying to initialize connection to %s...", device_path)
            fp = open(device_path, 'ab+', 0)
            _LOGGER.info("Setting connection mode...")
            fcntl.ioctl(fp, HIDIOCSFEATURE_9, bytearray.fromhex('00 c4 c6 c0 92 40 23 dc 96'))
            self._sensor_reader = SensorReader(fp)
        except FileNotFoundError as e:
            _LOGGER.warning("Did not find HID device. Is it plugged in? Message: %s", e)
            if fp is not None:
                fp.close()
            self._sensor_reader = None
        except Exception as e:
            _LOGGER.error("Device initialization failed: %s", e)
            if fp is not None:
                fp.close()
            self._sensor_reader = None

    def update(self):
        """Poll the latest sensor data."""
        if not self._sensor_reader:
            _LOGGER.info("Currently no device connected. Trying to find and connect to CO2 Device.")
            self._recover()
            if not self._sensor_reader:
                return {
                    "co2": None,
                    "temperature": None,
                    "humidity": None,
                    "available": False
                }

        _LOGGER.debug("Polling latest sensor data.")
        got_carbon_dioxide = False
        got_temperature = False
        got_humidity = False
        for _ in range(CONVERGENCE_SPEED):
            function, value = self._safe_poll_function_and_value()
            if function is None or value is None:
                continue
            if function == 0x50:
                if value > 10000:
                    # sometimes the first read of this value is something around 25k.
                    # This is a safety to filter such implausible readings
                    continue
                self.carbon_dioxide = value
                got_carbon_dioxide = True
            elif function == 0x42:
                self.temperature = value / 16.0 - 273.15
                got_temperature = True
            elif function == 0x41:
                self.humidity = value / 100
                got_humidity = True

        _LOGGER.debug(
            "Got new values for carbon_dioxide:%s temperature:%s humidity:%s",
            got_carbon_dioxide, got_temperature, got_humidity
        )
        return {
            # return all values, even if they are not the most recent
            "co2": self.carbon_dioxide,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "available": True
        }

    def _safe_poll_function_and_value(self):
        try:
            return self._sensor_reader.poll_function_and_value()
        except Exception as e:
            _LOGGER.warning("Error reading sensor data. Resetting device connection: %s", e)
            self.close()
            return None, None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up sensors from a config entry using the new DataUpdateCoordinator."""

    configured_path = entry.data.get("device_path")

    try:
        _, unique_id = await hass.async_add_executor_job(get_device_path)
    except Exception as e:
        if not configured_path:
            raise ConfigEntryNotReady("Could not setup device yet: %s" % e)
        # Custom path configured — we can proceed without auto-discovery
        unique_id = None
        _LOGGER.info(
            "Auto-discovery failed, using configured device path: %s",
            configured_path
        )

    reader = AirCO2ntrolReader(device_path=configured_path)

    async def async_update():
        _LOGGER.debug("async_update called")
        data = await hass.async_add_executor_job(reader.update)
        _LOGGER.debug("Fetched sensor data: %s", data)
        return data

    coordinator = DataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="AirCO2ntrol",
        update_method=async_update,
        update_interval=POLL_INTERVAL_TIMEDELTA
    )

    await coordinator.async_config_entry_first_refresh()

    # Store reader and coordinator for cleanup on unload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "reader": reader,
        "coordinator": coordinator,
    }

    device_info = DeviceInfo(
        identifiers={(DOMAIN, unique_id or entry.entry_id)},
        name="AirCO2ntrol",
        manufacturer="zyAura or TFA Dostmann",
        model="CO2 Monitor AIRCO2NTROL",
    )

    async_add_entities([
        AirCO2ntrolCarbonDioxideSensor(coordinator, unique_id, device_info),
        AirCO2ntrolTemperatureSensor(coordinator, unique_id, device_info),
        AirCO2ntrolHumiditySensor(coordinator, unique_id, device_info)
    ])


class AirCO2ntrolSensor(CoordinatorEntity, SensorEntity):
    """Base class for AirCO2ntrol sensors."""

    has_entity_name = True

    def __init__(self, coordinator, name, sensor_type, unit, icon, device_class, unique_id, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_unique_id = "%s-%s" % (unique_id, sensor_type)
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = device_info
        self.sensor_type = sensor_type

    @property
    def native_value(self):
        """Return the current sensor state."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.sensor_type)

    @property
    def available(self) -> bool:
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get("available", False)


class AirCO2ntrolCarbonDioxideSensor(AirCO2ntrolSensor):
    """CO2 Sensor."""

    def __init__(self, coordinator, unique_id, device_info):
        super().__init__(
            coordinator,
            name="Carbon Dioxide",
            sensor_type="co2",
            unit=CONCENTRATION_PARTS_PER_MILLION,
            icon="mdi:molecule-co2",
            device_class=SensorDeviceClass.CO2,
            unique_id=unique_id,
            device_info=device_info
        )


class AirCO2ntrolTemperatureSensor(AirCO2ntrolSensor):
    """Temperature Sensor."""

    def __init__(self, coordinator, unique_id, device_info):
        super().__init__(
            coordinator,
            name="Temperature",
            sensor_type="temperature",
            unit=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
            device_class=SensorDeviceClass.TEMPERATURE,
            unique_id=unique_id,
            device_info=device_info
        )


class AirCO2ntrolHumiditySensor(AirCO2ntrolSensor):
    """Humidity Sensor."""

    def __init__(self, coordinator, unique_id, device_info):
        super().__init__(
            coordinator,
            name="Humidity",
            sensor_type="humidity",
            unit=PERCENTAGE,
            icon="mdi:water-percent",
            device_class=SensorDeviceClass.HUMIDITY,
            unique_id=unique_id,
            device_info=device_info
        )
