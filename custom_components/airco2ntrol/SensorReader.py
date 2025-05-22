import logging

IDX_FNK = 0
IDX_MSB = 1
IDX_LSB = 2
IDX_CHK = 3

KEY = [0xc4, 0xc6, 0xc0, 0x92, 0x40, 0x23, 0xdc, 0x96]
CSTATE = [0x48, 0x74, 0x65, 0x6D, 0x70, 0x39, 0x39, 0x65]
SHUFFLE = [2, 4, 0, 7, 1, 6, 5, 3]

POLL_MODE_NORMAL = 'normal'
POLL_MODE_DECRYPT = 'decrypt'

_LOGGER = logging.getLogger(__name__)

def _decrypt(data):
    phase1 = [0] * 8
    for i, o in enumerate(SHUFFLE):
        phase1[o] = data[i]
    phase2 = [0] * 8
    for i in range(8):
        phase2[i] = phase1[i] ^ KEY[i]
    phase3 = [0] * 8
    for i in range(8):
        phase3[i] = ( (phase2[i] >> 3) | (phase2[ (i-1+8)%8 ] << 5) ) & 0xff
    ctmp = [0] * 8
    for i in range(8):
        ctmp[i] = ( (CSTATE[i] >> 4) | (CSTATE[i]<<4) ) & 0xff
    out = [0] * 8
    for i in range(8):
        out[i] = (0x100 + phase3[i] - ctmp[i]) & 0xff
    return out

class SensorReader:
    def __init__(self, fp):
        self._fp = fp
        self._mode = None

    def _init(self):
        _LOGGER.info("Trying to poll in 'normal' mode")
        data = self._poll_normal()
        if data is not None:
            _LOGGER.info("Setting poll mode to 'normal' mode")
            self._mode = POLL_MODE_NORMAL
            return

        _LOGGER.info("Trying to poll in 'decrypt' mode")
        data = self._poll_decrypt()
        if data is not None:
            _LOGGER.info("Setting poll mode to 'decrypt' mode")
            self._mode = POLL_MODE_DECRYPT
            return

        _LOGGER.warning("neither 'normal', nor 'decrypt' mode was successful")


    def poll_function_and_value(self):
        data = self._poll()
        if data is None:
            return None
        calculated_value = (data[IDX_MSB] << 8) | data[IDX_LSB]
        return data[IDX_FNK], calculated_value

    def _poll(self):
        if self._mode is None:
            self._init()

        if self._mode == POLL_MODE_NORMAL:
            return self._poll_normal()
        elif self._mode == POLL_MODE_DECRYPT:
            return self._poll_decrypt()

    def _poll_normal(self):
        data = list(self._fp.read(5))
        if ((data[IDX_MSB] + data[IDX_LSB] + data[IDX_FNK]) % 256) != data[IDX_CHK]:
            _LOGGER.info("Checksum incorrect for 'normal' mode: %s", data)
            return None
        else:
            return data

    def _poll_decrypt(self):
        data = list(self._fp.read(8))
        decrypted = _decrypt(data)
        if decrypted[4] != 0x0d or (sum(decrypted[:3]) & 0xff) != decrypted[3]:
            _LOGGER.info("Checksum incorrect for 'decrypt' mode: %s", data)
            return None
        else:
            return decrypted



