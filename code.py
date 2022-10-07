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
import supervisor

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

## TODO 2022-10-06
## See if the USB connection status logs properly to the text file when plugged into the wall
## If it does, then use that to remove the transit file with os.remove IF it's 5 minutes after file creation and usb_connected == True


led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

## CELL SETUP - SARA-R410M
## Set up pins for the cell device correctly in case we're plugged into it
power_pin = digitalio.DigitalInOut(board.D9)
power_pin.direction = digitalio.Direction.INPUT

reset_pin = digitalio.DigitalInOut(board.D10)
reset_pin.direction = digitalio.Direction.INPUT
#####################

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
    print("\nSENSOR DETECTED, attempting to writing to temperatures.txt, CIRCUITPY is read-only by computer")
    # storage.remount("", switch.value)
except ValueError:
    print("\nNO SENSOR, not writing to temperatures.txt CIRCUITPY is writable by computer")




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
        print('{},{},{}, usb:{}'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity, str(supervisor.runtime.usb_connected)))
        fp.write('{},{},{}, usb:{}\n'.format(timestring, ((sensor.temperature * 1.8) + 32), sensor.relative_humidity, str(supervisor.runtime.usb_connected)))
        fp.flush()
        fp.close()

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
            print("SUCCESS sending to Heat Seek at {}".format(timestring))
        else:
            print("Sending heatseek data failed")

        # Create an alarm that will trigger at the next reading interval seconds from now.
        print('Deep sleep for reading interval ({}) until the next send'.format( int(secrets["reading_interval"])))
        time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + int(secrets["reading_interval"]))
        # Exit the program, and then deep sleep until the alarm wakes us.
        alarm.exit_and_deep_sleep_until_alarms(time_alarm)
        # Does not return, so we never get here.
except OSError as e:  # Typically when the filesystem isn't writeable...
    if e.args[0] == 28:  # If the file system is full...
        print("\nERROR: filesystem full\n")
    print("\nWARN: not writing temp to file, or sending to Heat Seek")
    print("This is  likely because sensor is not attached and the filesystem was writable by USB")
    print("If this is unexpected, be sure you reset the feather after plugging in the sensor to run boot.py again.")
    print('Deep sleep for reading interval ({}) and try again'.format( int(secrets["reading_interval"])))
    time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + int(secrets["reading_interval"]))
    alarm.exit_and_deep_sleep_until_alarms(time_alarm)
    while True: 
        ## Code should never get here because we exit above
        print("waiting to sleep...")
        sleep(1)
