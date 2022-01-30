import board
import digitalio
import time
import adafruit_ahtx0
import busio

import alarm
import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
import rtc

## URL
HEATSEEK_URL = "http://relay.heatseek.org/temperatures"
CODE_VERSION = "F-ESP-1.3.0"

## TODO
## DONE Switch filesystem to read only if the sensor is attached
## DONE Switch back to writeable filesystem if sensor is detached (or other switch? battery attached?)
## DONE Write temperatures to the file
## DONE temperatures to the Heatseek service
## TODO set a variable in sleep memory to test if RTC is persistent across deep sleep
## TODO Write separate log and queue files
## TODO Write out all readings in the queue
## TODO deep sleep if year == 2000 and couldn't fetch time

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

print("Starting up, blink slow then fast for 6 sec")
for x in range(8):
    led.value = not led.value
    time.sleep(0.25)
for x in range(8):
    led.value = not led.value
    time.sleep(0.5)

print("Blinking done, now startinging the program")
## Set up the realtime clock
r = rtc.RTC()
print(f"Time at start: {r.datetime}")

try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = adafruit_ahtx0.AHTx0(i2c)
    # If the sensor is connected, go to read only mode so we can write temperatures
    print("Sensor detected, writing to temperatures.txt, CIRCUITPY is readonly by computer")
    # storage.remount("", switch.value)
except ValueError:
    print("No sensor, not writing to temperatures.txt CIRCUITPY is writable by computer")




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

## Set up http request objects
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

## Set the time if this is a cold boot
if not alarm.wake_alarm:
    print("Cold boot. Fetching updated time and setting realtime clock")

    response = requests.get("http://worldtimeapi.org/api/timezone/America/New_York")
    if response.status_code == 200:
        r.datetime = time.localtime(response.json()['unixtime'] + response.json()['raw_offset'])
        print(f"System Time: {r.datetime}")
    else:
        print("Setting time failed")
else:
    print("Waking up from sleep, RTC value after deep sleep was ")
    print(f"System Time: {r.datetime}")



try:
    with open("/temperature.txt", "a") as fp:
        # do the C-to-F conversion here if you would like
        print("writing to file")
        timestring = '{}-{}-{} {}:{}:{}'.format(r.datetime.tm_year, r.datetime.tm_mon, r.datetime.tm_mday, r.datetime.tm_hour, r.datetime.tm_min, r.datetime.tm_sec)
        print('{},{},{}'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
        fp.write('{},{},{}\n'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
        fp.flush()

        # sensor.temperature
        # sensor.relative_humidity

        heatseek_data = {
            "hub":"featherhub",
            "cell": secrets["cell_id"],
            "time": time.time(),
            "temp": ((sensor.temperature * 1.8) + 32),
            "humidity": sensor.relative_humidity,
            "sp": secrets["reading_interval"],
            "cell_version": CODE_VERSION,
        }

        response = requests.post(HEATSEEK_URL, data=heatseek_data)
        if response.status_code == 200:
            print(f"System Time: {r.datetime}")
        else:
            print("Sending heatseek data failed")

        # Create an alarm that will trigger at the next reading interval seconds from now.
        
        time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + int(secrets["reading_interval"]))
        # Exit the program, and then deep sleep until the alarm wakes us.
        alarm.exit_and_deep_sleep_until_alarms(time_alarm)
        # Does not return, so we never get here.
except OSError as e:  # Typically when the filesystem isn't writeable...
    if e.args[0] == 28:  # If the file system is full...
        print("filesystem full")
    print("not writing temp to file")
    print("Deep sleep for 1 hour and try again")
    time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + 3600)
    alarm.exit_and_deep_sleep_until_alarms(time_alarm)
    while True: 
        ## Code should never get here because we exit above
        print("waiting to sleep...")
        sleep(1)
