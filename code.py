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
import os 
from adafruit_lc709203f import LC709203F

# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise


def deep_sleep(secs):
    # go to sleep for an hour and see if it's time to wake up from quiet mode next time
    time_to_wake = time.monotonic() + secs
    # set the time alarm, notice that monotonic_time here is a named argument and must be set in the function call
    time_alarm = alarm.time.TimeAlarm(monotonic_time=time_to_wake)
    # Exit the program, and then deep sleep until the alarm wakes us.
    alarm.exit_and_deep_sleep_until_alarms(time_alarm)
## END OF FUNCTION deep_sleep

def handle_quiet_mode(new_voltage):
    # return if no file
    if 'quiet.txt' not in os.listdir(): return
    print("QUIET MODE DETECTED - quiet.txt exists, checking voltage against battery.txt")
    # Okay, we've got a quiet.txt. Sleep unless the battery is charging
    # See quiet.txt.example for more info
    if 'battery.txt' in os.listdir():
        f = open('battery.txt',"r")
        ## get and parse it's data
        last_voltage = f.read().splitlines()[0]
        f.close()
        print('QUIET MODE DATA - new voltage:{}, last_voltage:{}'.format(new_voltage, last_voltage))
        if(new_voltage > float(last_voltage) + 0.12):
            print("QUIET MODE ENDED - battery is charging. Unit must be plugged in")
            print("Clearing battery.txt and quiet.txt")
            # Higher voltage even with some offset! We're plugged in
            # and charging. Clear the quiet and return. 
            os.remove('battery.txt')
            os.remove('quiet.txt')
            return
        else:
            # Lower voltage, update the battery.txt file
            if(new_voltage < float(last_voltage)):
                # overwrite file with new lower voltages, don't write higher voltages
                # we're keeping a "low water mark" here
                print("QUIET MODE: overwriting battery.txt low water mark")
                with open('battery.txt', "w") as bf:
                    bf.write('{}\n'.format(new_voltage))
            # Either way, go to sleep for an hour and see if it's time to wake up from quiet mode next time
            time_to_wake = time.monotonic() + 3600
            # set the time alarm, notice that monotonic_time here is a named argument and must be set in the function call
            time_alarm = alarm.time.TimeAlarm(monotonic_time=time_to_wake)
            # Exit the program, and then deep sleep until the alarm wakes us.
            print("QUIET MODE: Sleeping for 1 hr")
            alarm.exit_and_deep_sleep_until_alarms(time_alarm)
    else:
        print("QUIET MODE: writing new battery.txt")
        with open('battery.txt', "w") as bf:
            bf.write('{}\n'.format(new_voltage))
            print("QUIET MODE: Sleeping for 1 hr")
            deep_sleep(3600)
            
## END OF FUNCTION handle_quiet_mode


def transmit_queue(requests):
    print("Entered function: transmit_queue")
    if 'queue' not in os.listdir(): return
    qfiles = os.listdir('/queue/')
    for qfile in qfiles:
        if not qfile.startswith('1'):
            print('Removing extraneous file in queue /queue/{}'.format(qfile))
            os.remove('/queue/{}'.format(qfile))
        if not qfile.endswith('.txt'):
            print('Removing extraneous file in queue /queue/{}'.format(qfile))
            os.remove('/queue/{}'.format(qfile))
        ## File looks legit, open it
        print("opening queued file /queue/{}".format(qfile))
        f = open('/queue/{}'.format(qfile),"r")
        ## get and parse it's data
        qdata = f.read().splitlines()[0].split(',')
        f.close()
        ## make our heatseek data object with that queued data
        heatseek_data = {
            "hub":"featherhub",
            "cell": secrets["cell_id"],
            "time": qdata[0],
            "temp": qdata[1],
            "humidity": qdata[2],
            "sp": secrets["reading_interval"],
            "cell_version": CODE_VERSION,
        }
        ## try sending it, we already know we have a connection or we 
        ## wouldn't get to the transmit_queue function
        send_success = False
        print("Sending queued data file /queue/{}".format(qfile))
        response = requests.post(HEATSEEK_URL, data=heatseek_data)
        if response.status_code == 200:
            print("SUCCESS sending queued to Heat Seek at {}".format(time.time()))
            send_success = True
            os.remove('/queue/{}'.format(qfile))
        else:
            print("Sending queued heatseek data failed")
            return False
## END OF FUNCTION - transmit_queue(requests)

## URL
HEATSEEK_URL = "http://relay.heatseek.org/temperatures"
CODE_VERSION = "F-ESP-1.3.0"

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

## Check on the battery
print("LC709203F simple test")
print("Make sure LiPoly battery is plugged into the board!")

battery_sensor = LC709203F(board.I2C())

print("IC version:", hex(battery_sensor.ic_version))
print("Battery: Mode: %s / %0.3f Volts / %0.1f %%" % (battery_sensor.power_mode, battery_sensor.cell_voltage, battery_sensor.cell_percent))

try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = adafruit_ahtx0.AHTx0(i2c)
    # If the sensor is connected, go to read only mode so we can write temperatures
    print("\nSENSOR DETECTED, attempting to writing to temperatures.txt, CIRCUITPY is read-only by computer")
    # storage.remount("", switch.value)
except ValueError:
    print("\nNO SENSOR, not writing to temperatures.txt CIRCUITPY is wrietable by computer")


reading_interval = int(secrets["reading_interval"])
net_connected = False
try: 
    print("Connecting to %s"%secrets["ssid"])
    wifi.radio.connect(secrets["ssid"], secrets["password"])
    print("Connected to %s!"%secrets["ssid"])
    print("My IP address is", wifi.radio.ipv4_address)

    ## Set up http request objects
    pool = socketpool.SocketPool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    net_connected = True
    ## Set the time if this is a cold boot
    if not alarm.wake_alarm:
        print("Cold boot. Fetching updated time and setting realtime clock")

        response = requests.get("http://worldtimeapi.org/api/timezone/America/New_York")
        if response.status_code == 200:
            r.datetime = time.localtime(response.json()['unixtime'])
            print(f"System Time: {r.datetime}")
        else:
            print("Setting time failed")
    else:
        print("Waking up from sleep, RTC value after deep sleep was ")
        print(f"System Time: {r.datetime}")
except ConnectionError:
    print("Could not connect to network.")
    net_connected = False


# ensure the time matches the RTC's time
time.struct_time(r.datetime)

## Check if the time is valid 
##   (greater than oct 10 2022 timestamp 1665240748), sleep if not
if(time.time() < 1665240748):
    print('Time is invalid. Sleeping for 5 minutes')
    deep_sleep(300)

## We have a valid time, write out temperature.txt and try to transmit
try:
    with open("/temperature.txt", "a") as fp:
        # do the C-to-F conversion here if you would like
        print("writing to file")
        print('{},{},{},{},{}'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity, battery_sensor.power_mode, battery_sensor.cell_voltage))
        fp.write('{},{},{},{},{}\n'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity, battery_sensor.power_mode, battery_sensor.cell_voltage))
        fp.flush()
        fp.close()

    handle_quiet_mode(battery_sensor.cell_voltage)

    heatseek_data = {
        "hub":"featherhub",
        "cell": secrets["cell_id"],
        "time": time.time(),
        "temp": ((sensor.temperature * 1.8) + 32),
        "humidity": sensor.relative_humidity,
        "sp": secrets["reading_interval"],
        "cell_version": CODE_VERSION,
    }
    send_success = False
    if(net_connected): 
        response = requests.post(HEATSEEK_URL, data=heatseek_data)
        if response.status_code == 200:
            print("SUCCESS sending to Heat Seek at {}".format(time.time()))
            send_success = True
            transmit_queue(requests)
        else:
            print("Sending heatseek data failed")


    if(send_success == False):
        if 'queue' not in os.listdir():
            os.mkdir('queue')
        with open("/queue/{}.txt".format(time.time()), "a") as qp:
            print("Couldn't send, writing a queue file")
            print('{},{},{}'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
            qp.write('{},{},{}\n'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
            qp.flush()
            qp.close()

    # Create an alarm that will trigger at the next reading interval seconds from now.
    print('Deep sleep for reading interval ({}) until the next send'.format( reading_interval))
    deep_sleep(reading_interval)
except OSError as e:  # Typically when the filesystem isn't writeable...
    if e.args[0] == 28:  # If the file system is full...
        print("\nERROR: filesystem full\n")
    print("\nWARN: not writing temp to file, or sending to Heat Seek")
    print("This is  likely because sensor is not attached and the filesystem was writable by USB")
    print("If this is unexpected, be sure you reset the feather after plugging in the sensor to run boot.py again.")
    print('Deep sleep for reading interval ({}) and try again'.format(reading_interval))
    deep_sleep(reading_interval)
