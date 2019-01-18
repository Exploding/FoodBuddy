# Listens to a serial port for weight updates from a shelf module
import serial
import threading
import time
import Queue
import datetime
import json

import globals

class shelfListenerThread (threading.Thread):
    def __init__(self, threadID, name, serialPort, q, qL):
        threading.Thread.__init__(self, group=None)
        self.threadID = threadID
        self.name = name 
        self.serialPort = serialPort
        self.weight = 0
        self.q = q
        self.qL = qL
        self.conf = json.load(open('conf.json'))
        self.stopEvent = threading.Event()
    def stop(self):
        self.stopEvent.set()
    def run(self):
        print "Starting " + self.name
        self.readSerial()
        print "Exiting " + self.name
    def readSerial(self): 
        while not self.stopEvent.is_set():
            if self.serialPort.isOpen():
                # read the next value from the serial port
                val = ''
                try:
                    val = self.serialPort.readline()
                    val = int(float(val.decode('utf-8')))
                except:
                    print globals.bcolors.FAIL + self.name + '|failed to read from serial port' + globals.bcolors.ENDC
                    continue

                # if this is the first pass, zero the weight
                if self.weight == 0:
                    self.weight = val
           
                # calculate the change in weight
                delta = val - self.weight

                # only process if the weight change is over a certain weight threshold (to filter out noise and weight fluttering)
                if abs(delta) >= self.conf['weight_threshold']:
                    print globals.bcolors.OKBLUE + self.name + '|weight updated' + globals.bcolors.ENDC
                    self.qL.acquire()
                    self.q.put({
                        "timestamp": datetime.datetime.now(), 
                        "type": "shelf-update",
                        "action": ("item removed" if (self.weight > val) else "item added"),
                        "value": delta,
                        "shelf": self.threadID
                    })
                    self.qL.release()
                    print self.weight
                # always update the current weight, regardless if the delta is within the weight thresold (weight tends to drift up or down over time)
                self.weight = val