import board
import digitalio
import time
import adafruit_ahtx0
import busio

import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
import rtc

## TODO
## Switch filesystem to read only if the sensor is attached
## Switch back to writeable filesystem if sensor is detached (or other switch? battery attached?)
## Write temperatures to the file
## Write temperatures to the Heatseek service
## Write a time file (bytearray in NVM?) and figure out how to keep count

try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = adafruit_ahtx0.AHTx0(i2c)
    # If the sensor is connected, go to read only mode so we can write temperatures
    print("sensor detected in code.py")
    # storage.remount("", switch.value)
except ValueError:
    print("no sensor in code.py")

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# URLs to fetch from
TEXT_URL = "http://wifitest.adafruit.com/testwifi/index.html"
JSON_QUOTES_URL = "https://www.adafruit.com/api/quotes.php"
JSON_STARS_URL = "https://api.github.com/repos/adafruit/circuitpython"

# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise


print("Connecting to %s"%secrets["ssid"])
wifi.radio.connect(secrets["ssid"], secrets["password"])
print("Connected to %s!"%secrets["ssid"])
print("My IP address is", wifi.radio.ipv4_address)

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

print("Fetching and parsing json from", JSON_STARS_URL)
response = requests.get(JSON_STARS_URL)
print("-" * 40)
print("CircuitPython GitHub Stars", response.json()["stargazers_count"])
print("-" * 40)

response = requests.get("http://worldtimeapi.org/api/timezone/America/New_York")
if response.status_code == 200:
    r = rtc.RTC()
    r.datetime = time.localtime(response.json()['unixtime'] + response.json()['raw_offset'])
    print(f"System Time: {r.datetime}")
else:
    print("Setting time failed")


try:
    with open("/temperature.txt", "a") as fp:
        while True:
            # do the C-to-F conversion here if you would like
            print("writing to file")
            timestring = '{}-{}-{} {}:{}:{}'.format(r.datetime.tm_year, r.datetime.tm_mon, r.datetime.tm_mday, r.datetime.tm_hour, r.datetime.tm_min, r.datetime.tm_sec)
            print('{},{},{}'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
            fp.write('{},{},{}\n'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
            fp.flush()
            led.value = not led.value
            time.sleep(1)
except OSError as e:  # Typically when the filesystem isn't writeable...
    if e.args[0] == 28:  # If the file system is full...
        print("filesystem full")
    print("not writing temp to file")


#while True:
#    print("\nTemperature: %0.1f C" % sensor.temperature)
#    print("Humidity: %0.1f %%" % sensor.relative_humidity)
#    time.sleep(3)

