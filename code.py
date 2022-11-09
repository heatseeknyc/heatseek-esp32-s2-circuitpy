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
import neopixel 
from adafruit_lc709203f import LC709203F
import adafruit_requests as requests
from adafruit_fona.adafruit_fona import FONA
from adafruit_fona.fona_3g import FONA3G
import adafruit_fona.adafruit_fona_network as network
import adafruit_fona.adafruit_fona_socket as cellular_socket

pixels = neopixel.NeoPixel(board.NEOPIXEL, 1)


# SKIFF NOTES 2022-11-06
# When testing on the REPL, to paste code segments, ctrl-e puts you into paste mode
# then paste your code with cmd-c/cmd-v 
# then hit ctrl-d and hit enter. 

# DONE: refactor to skip networking stuff and send SMS instead
# TODO: handle queue 
# TODO: SMS receiver

##################
## Set pins to safe values in case the sms board is attached
###################

power_pin = digitalio.DigitalInOut(board.D9)
power_pin.direction = digitalio.Direction.INPUT

reset_pin = digitalio.DigitalInOut(board.D10)
reset_pin.direction = digitalio.Direction.INPUT

LTE_SHIELD_POWER_PULSE_PERIOD = 3.2
LTE_RESET_PULSE_PERIOD = 10.0
## SMS relay number - should be a twilio number and entered as an integer with country code
SMS_RELAY_NUMBER = 16469709199
SMS_QUEUE_LENGTH = 2

###########
# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

## URL
HEATSEEK_URL = "http://relay.heatseek.org/temperatures"
CODE_VERSION = "F-ESP-1.3.2"
VOLT_DIFF_FOR_CHARGE = 0.03
QUIET_MODE_SLEEP_LENGTH = 600

## FUNCTIONS



def init_sms_board():
    print("Initializing the Cell board with a power pulse")
    # Initialize the modem
    power_pin.switch_to_output()
    power_pin.value = False
    time.sleep(LTE_SHIELD_POWER_PULSE_PERIOD)
    # power_pin.switch_to_input()

    uart = busio.UART(board.TX, board.RX, baudrate=9600)
    # uart = board.UART()
    global fona 
    fona = FONA(uart, reset_pin)
    # Initialize cellular data network
    global network
    net = network.CELLULAR(fona, ("ting", '', ''))
    while not net.is_attached:
        print("Attaching to network...")
        time.sleep(0.5)
    print("Attached!")
    time.sleep(0.5)
## END OF FUNCTION init_sms_board

def deep_sleep(secs):
    fade_status(0, 0, 128, 3, 1)
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
        if(new_voltage > float(last_voltage) + VOLT_DIFF_FOR_CHARGE):
            fade_up_status(128, 128, 128, 4, 1)
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
            flash_status(80, 0, 128, 2, 1)
            print("QUIET MODE: Sleeping for "+ str(QUIET_MODE_SLEEP_LENGTH / 60) + " min")
            deep_sleep(QUIET_MODE_SLEEP_LENGTH)
    else:
        print("QUIET MODE: writing new battery.txt")
        with open('battery.txt', "w") as bf:
            bf.write('{}\n'.format(new_voltage))
            flash_status(80, 0, 128, 2, 1)
            print("QUIET MODE: Sleeping for "+ str(QUIET_MODE_SLEEP_LENGTH / 60) + " min")
            deep_sleep(QUIET_MODE_SLEEP_LENGTH)
            
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

def transmit_sms_queue():
    print("Entered function: transmit_sms_queue")
    if 'queue' not in os.listdir(): return
    qfiles = os.listdir('/queue/')
    heatseek_json = '{{"c":"{}","i":"{}","r":['.format(secrets["cell_id"], secrets["reading_interval"])
    heatseek_json_ar = []
    ## Get the files in batches of 2
    for qfile in qfiles[0:SMS_QUEUE_LENGTH]:
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
        
        heatseek_json_ar.append('{{"ti":"{}","te":"{}","h":"{}"}}'.format((int(qdata[0]) - 1667875724), round((float(qdata[1])),1), round(float(qdata[2]),1)))
    heatseek_json += (",".join(heatseek_json_ar))
    heatseek_json += ']}'
    send_success = False
    send_success = fona.send_sms(SMS_RELAY_NUMBER, str(heatseek_json))
    if send_success:
        print("SUCCESS sending queued to Heat Seek at {}".format(time.time()))
        for qfile in qfiles[0:SMS_QUEUE_LENGTH]:
            os.remove('/queue/{}'.format(qfile))
        qfiles = os.listdir('/queue/')
        if len(qfiles) > 0:
            transmit_sms_queue()
        # TODO: call this again recursively if we still have files
        return True
    else:
        print("Sending queued heatseek data failed")
        return False
## END OF FUNCTION - transmit_sms_queue(requests)

def clear_queued_files():
    if 'queue' not in os.listdir(): return
    qfiles = os.listdir('/queue/')
    for qfile in qfiles:
        os.remove('/queue/{}'.format(qfile))

def write_queue_file():
    if 'queue' not in os.listdir():
        os.mkdir('queue')
    with open("/queue/{}.txt".format(time.time()), "a") as qp:
        fade_status(128, 128, 0, 2, 2)
        print("Couldn't send or batching SMS msgs, writing a queue file")
        print('{},{},{}'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
        qp.write('{},{},{}\n'.format(time.time(), ((sensor.temperature * 1.8) + 32), sensor.relative_humidity))
        qp.flush()
        qp.close()

def flash_status(red=128, green=128, blue=128, flash_length=0.5, repeat=1):
    for x in range(0, repeat):
        pixels.fill((red, green, blue))
        time.sleep(flash_length)
        pixels.fill((0, 0, 0))
        time.sleep(flash_length)

def flash_warning(red=128, green=0, blue=0, red2=128, green2=128, blue2=0,flash_length=0.5, repeat=4):
    for x in range(0, repeat):
        pixels.fill((red, green, blue))
        time.sleep(flash_length)
        pixels.fill((red2, green2, blue2))
        time.sleep(flash_length)
    pixels.fill((0, 0, 0))


def fade_status(red=0, green=0, blue=128, fade_length=2, repeat=1):
    for x in range(0, repeat):
        for y in range(100, 1, -1):
            pixels.fill((int(pow(red, y/100)), int(pow(green, y/100)), int(pow(blue, y/100))))
            time.sleep(fade_length / 100)
    pixels.fill((0, 0, 0))    


def fade_up_status(red=128, green=128, blue=128, fade_length=2, repeat=1):
    for x in range(0, repeat):
        for y in range(1, 100):
            pixels.fill((int(pow(red, y/100)), int(pow(green, y/100)), int(pow(blue, y/100))))
            time.sleep(fade_length / 100)
    pixels.fill((0, 0, 0))  

## MAIN CODE BLOCK

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


print("Starting up, blink slow then fast for 6 sec")
for x in range(8):
    led.value = not led.value
    time.sleep(0.5)
for x in range(8):
    led.value = not led.value
    time.sleep(0.5)

print("Blinking done, now startinging the program")
## Set up the realtime clock
r = rtc.RTC()
print(f"Time at start: {r.datetime}")

if (secrets['sms_mode'] == "true"):
    init_sms_board()
    try:
        r.datetime = time.localtime(fona.get_timestamp())
    except:
        flash_warning()
    print(f"Time after getting fona time: {r.datetime}")

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
    flash_status(0,128,0,1,1)
    # storage.remount("", switch.value)
except ValueError:
    print("\nNO SENSOR, not writing to temperatures.txt CIRCUITPY is writeable by computer")
    flash_status(0,0,128,1,1)

reading_interval = int(secrets["reading_interval"])
net_connected = False
if (secrets['sms_mode'] != "true"):
    try: 
        ## #########
        ## Internal "try" statement attempts to connect to both the tenant wifi
        ## and the heatseek wifi, so that in almost all cases we get a valid datetime
        ## on first boot and can use that to keep time during transit
        try:
            print("Connecting to %s"%secrets["tenant_wifi_ssid"])
            wifi.radio.connect(secrets["tenant_wifi_ssid"], secrets["tenant_wifi_password"])
            print("Connected to %s!"%secrets["tenant_wifi_ssid"])
            print("My IP address is", wifi.radio.ipv4_address)

            ## Set up http request objects
            pool = socketpool.SocketPool(wifi.radio)
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
            net_connected = True
            flash_status(0,128,0,0.5,2)
        except: 
            print("Connecting to fallback network %s"%secrets["heatseek_wifi_ssid"])
            wifi.radio.connect(secrets["heatseek_wifi_ssid"], secrets["heatseek_wifi_password"])
            print("Connected to %s!"%secrets["heatseek_wifi_ssid"])
            print("My IP address is", wifi.radio.ipv4_address)
            ## Set up http request objects
            pool = socketpool.SocketPool(wifi.radio)
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
            net_connected = True
            flash_status(0,128,0,0.5,2)
            
        ## Set the time if this is a cold boot
        if not alarm.wake_alarm:
            print("Cold boot. Fetching updated time and setting realtime clock")
            fade_up_status(0,128,0,3,1)
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
        flash_warning()
        net_connected = False
    except ValueError:
        print("Time response was invalid (no connection or bad data)")
        flash_warning()
        net_connected = False
    except:
        print("An error occured connecting to the network or time server")
        flash_warning()
        net_connected = False

# ensure the time matches the RTC's time
time.struct_time(r.datetime)

## Check if the time is valid 
##   (greater than oct 10 2022 timestamp 1665240748), sleep if not
if(time.time() < 1665240748):
    print('Time is invalid. Sleeping for ' + str(QUIET_MODE_SLEEP_LENGTH / 60) + ' minutes')
    deep_sleep(QUIET_MODE_SLEEP_LENGTH)

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

    if (secrets['sms_mode'] == "true"):
        write_queue_file()
        if 'queue' in os.listdir(): 
            qfiles = os.listdir('/queue/')
            if len(qfiles) >= SMS_QUEUE_LENGTH: 
                send_success = transmit_sms_queue()
    elif(net_connected): 
        response = requests.post(HEATSEEK_URL, data=heatseek_data)
        if response.status_code == 200:
            print("SUCCESS sending to Heat Seek at {}".format(time.time()))
            send_success = True
            flash_status(128,128,128, 0.5, 3)
            transmit_queue(requests)
        else:
            print("Sending heatseek data failed")

        if(send_success == False):
            write_queue_file()

    # Create an alarm that will trigger at the next reading interval seconds from now.
    print('Deep sleep for reading interval ({}) until the next send'.format( reading_interval))
    deep_sleep(reading_interval)
except OSError as e:  # Typically when the filesystem isn't writeable...
    if e.args[0] == 28:  # If the file system is full...
        print("\nERROR: filesystem full\n")
    flash_warning()
    print("\nWARN: not writing temp to file, or sending to Heat Seek")
    print("This is  likely because sensor is not attached and the filesystem was writable by USB")
    print("If this is unexpected, be sure you reset the feather after plugging in the sensor to run boot.py again.")
    print('Deep sleep for reading interval ({}) and try again'.format(reading_interval))
    deep_sleep(reading_interval)
