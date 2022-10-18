# Write your code here :-)
"""CircuitPython Essentials Storage logging boot.py file"""
import board
import digitalio
import storage
import adafruit_ahtx0
import rtc

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

## CELL SETUP - SARA-R410M
## Set up pins for the cell device correctly in case we're plugged into it
power_pin = digitalio.DigitalInOut(board.D9)
power_pin.direction = digitalio.Direction.INPUT

reset_pin = digitalio.DigitalInOut(board.D10)
reset_pin.direction = digitalio.Direction.INPUT
#####################

## Set up the realtime clock
r = rtc.RTC()
print(f"Time at start: {r.datetime}")

try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = adafruit_ahtx0.AHTx0(i2c)
    # If the sensor is connected, go to read only mode so we can write temperatures
    print("sensor detected, going read-only")
    storage.remount("/", False)
except ValueError:
    print("no sensor, allow circuitpython writing")



