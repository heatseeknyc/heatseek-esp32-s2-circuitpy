# Write your code here :-)
"""CircuitPython Essentials Storage logging boot.py file"""
import board
import digitalio
import storage
import board
import adafruit_ahtx0

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

try:
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = adafruit_ahtx0.AHTx0(i2c)
    # If the sensor is connected, go to read only mode so we can write temperatures
    print("sensor detected, going read-only")
    storage.remount("/", False)
except ValueError:
    print("no sensor, allow circuitpython writing")



