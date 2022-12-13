"""main.py
"Frimware for ESP32.
"Frimware reads data from sensors and sends to the cloud
"Last update 13.12.22
"""

from machine import I2C, Pin, Timer
from machine import UART
import time
import network
from uthingsboard.client import TBDeviceMqttClient
import sys
import settings

"""Temperature sensor"""


class HTU21D(object):
    ADDRESS = 0x40
    ISSUE_TEMP_ADDRESS = 0xE3
    ISSUE_HU_ADDRESS = 0xE5

    def __init__(self):
        """Initiate the HUT21D"""
        self.i2c = I2C(scl=Pin(settings.SCL_Pin), sda=Pin(settings.SDA_Pin), freq=100000)

    def _crc_check(self, value):
        """CRC check data
        Notes:
            stolen from https://github.com/sparkfun/HTU21D_Breakout

        Args:
            value (bytearray): data to be checked for validity
        Returns:
            True if valid, False otherwise
        """
        remainder = ((value[0] << 8) + value[1]) << 8
        remainder |= value[2]
        divsor = 0x988000

        for i in range(0, 16):
            if remainder & 1 << (23 - i):
                remainder ^= divsor
            divsor >>= 1

        if remainder == 0:
            return True
        else:
            return False

    def _issue_measurement(self, write_address):
        """Issue a measurement.
        Args:
            write_address (int): address to write to
        :return:
        """
        self.i2c.start()
        self.i2c.writeto_mem(int(self.ADDRESS), int(write_address), '')
        self.i2c.stop()
        time.sleep_ms(50)
        data = bytearray(3)
        self.i2c.readfrom_into(self.ADDRESS, data)
        if not self._crc_check(data):
            raise ValueError()
        raw = (data[0] << 8) + data[1]
        raw &= 0xFFFC
        return raw

    @property
    def temperature(self):
        """Calculate temperature"""
        raw = self._issue_measurement(self.ISSUE_TEMP_ADDRESS)
        return -46.85 + (175.72 * raw / 65536)

    @property
    def humidity(self):
        """Calculate humidity"""
        raw = self._issue_measurement(self.ISSUE_HU_ADDRESS)
        return -6 + (125.0 * raw / 65536)


"""C02 sensor"""


class S8ModBus(object):

    # Initialization
    def __init__(self):
        self.uart = UART(1, 9600)
        self.uart.init(9600, bits=8, parity=None, stop=1, tx=settings.TX_Pin, rx=settings.RX_Pin, timeout=1000)
        # NB! Note that this is a specific configuration. Make sure you attach the sensor
        # to the correct pins on the ESP32 board

    # Get status and reading
    def get_status_and_co2_reading(self):
        cmd = b'\xfe\x04\x00\x00\x00\x04'
        crc = self.compute_crc(cmd)
        self.uart.write(cmd + crc)
        resp = self.uart.read()

        check_crc = self.compute_crc(resp[:-2])
        if check_crc != resp[-2:]:
            raise ValueError("CRC mismatch. Problem with sensor communication?")

        # If all is well, return the status register (first byte only) and the CO2 reading
        return resp[3], int.from_bytes(resp[9:11], 'big')

    # Corresponding property
    @property
    def co2(self):
        data = self.get_status_and_co2_reading()
        return data[1]

    # Compute CRC
    @staticmethod
    def compute_crc(msg):
        crc = 0xffff
        for b in msg:
            crc ^= b
            for i in range(8):
                if (crc & 0x0001) != 0:
                    crc >>= 1
                    crc ^= 0xa001
                else:
                    crc >>= 1
        return crc.to_bytes(2, 'little')


def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.disconnect()
    wifi.connect(settings.WIFI_SSID, settings.WIFI_PASSWORD)
    if not wifi.isconnected():
        print('connecting..')
        timeout = 0
        while (not wifi.isconnected() and timeout < 5):
            print(5 - timeout)
            timeout = timeout + 1
            time.sleep(1)
    if (wifi.isconnected()):
        print('connected')
    else:
        print('not connected')
        sys.exit()


if __name__ == '__main__':
    """Connected to network and initialize sensors"""
    connect_wifi()
    s8 = S8ModBus()
    th = HTU21D()

    """Run the program"""
    while True:
        """Connect to the cloud for data transfer"""
        client = TBDeviceMqttClient('demo.thingsboard.io', access_token=settings.ACCESS_TOKEN)
        client.connect()

        """Transferring data from sensors"""
        telemetry = {'CO2': float(s8.co2), 'Temperature': float(th.temperature), 'Humidity': float(th.humidity)}
        client.send_telemetry(telemetry)

        """Check if the server has any pending messages."""
        client.check_msg()

        """Print data to console """
        print("CO2: ", s8.co2)
        print(f"Temperature and humidity readings: {th.temperature} and {th.humidity}")

        """Close the server"""
        client.disconnect()

        """Wait 1 second and transerf data again"""
        time.sleep_ms(1000)
