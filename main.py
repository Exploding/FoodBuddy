import serial
import threading
import time
import Queue
import pprint
import json
import datetime
from SimpleWebSocketServer import SimpleWebSocketServer

from shelfListener import shelfListenerThread
from objectLabeler import objectLabelingThread
from websocketServer import SimpleServer

import globals

def main():
    # load configuration
    conf = json.load(open('conf.json'))

    # initialize bluetooth on the channel 1
    bluetoothSerial = serial.Serial( "/dev/rfcomm0", baudrate=9600 )

    # create a new event queue
    workQueue = Queue.Queue(10)
    queueLock = threading.Lock()

    # init and start the first shelf listener thread
    shelf1Listener = shelfListenerThread(1,"Shelf-Thread-1",bluetoothSerial, workQueue, queueLock)
    shelf1Listener.start()

    # init and start the google automl object labeling thread
    objectLabeler = objectLabelingThread(2, "Object-Labeler-Thread", workQueue, queueLock)
    objectLabeler.start()

    # start the websocket server
    server = SimpleWebSocketServer('', 8000, SimpleServer)
    serverThread = threading.Thread(target = runServer, args=(server,))
    serverThread.start()
    print 'Starting websocket server thread'

    # keep track of the last shelf and motion detection events
    lastObjectDetected = None
    lastWeightChange = None

    try:
        # constantly check the event queue for motion and shelf weight change events
        while True:
            queueLock.acquire()
            if not workQueue.empty():
                data = workQueue.get()
                pprint.pprint(data)
                
                # update the last event of each type to happen
                if data['type'] == 'object-detected':
                    lastObjectDetected = data
                if data['type'] == 'shelf-update':
                    lastWeightChange = data
            queueLock.release()
            
            # if both events have not yet happened, just continue
            if lastObjectDetected is None or lastWeightChange is None:
                continue

            # if the time of the last two events is less than the event threshold, we can associate the events
            if abs((lastObjectDetected['timestamp'] - lastWeightChange['timestamp']).total_seconds()) <= conf['event_threshold']:
                print globals.bcolors.OKGREEN + 'Main Thread|sending update to websocket clients' + globals.bcolors.ENDC
                sendDataToClients({
                    'item': lastObjectDetected['value'],
                    'weight': lastWeightChange['value'],
                    'timestamp': str(lastWeightChange['timestamp'])
                })
                lastObjectDetected = None
                lastWeightChange = None
    except KeyboardInterrupt:
        shelf1Listener.stop()
        objectLabeler.stop()
        stopServer()
        shelf1Listener.join()
        objectLabeler.join()
        serverThread.join()
        print "all threads closed"

def sendDataToClients(data):
    print globals.bcolors.OKGREEN 
    pprint.pprint(data)
    print globals.bcolors.ENDC
    
    for client in globals.clients:
        client.sendMessage(unicode(json.dumps(data, default = jsonConverter), 'utf-8'))

def jsonConverter(o):
    if isinstance(o, datetime.datetime):
        return o.__str__()

def runServer(server):
    while not globals.stopServerEvent:
        server.serveonce()
    print 'Stopping websocket server'

def stopServer():
    globals.stopServerEvent = True

if __name__ == '__main__':
    main()
    
print 'exiting main thread'