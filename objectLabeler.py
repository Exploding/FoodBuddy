# USAGE
# python pi_surveillance.py --conf conf.json

# import the necessary packages
from pyimagesearch.tempimage import TempImage
from picamera.array import PiRGBArray
from picamera import PiCamera
import argparse
import warnings
import datetime
import imutils
import json
import time
import cv2
import serial
import threading
import time
import Queue
import RPi.GPIO as GPIO

from google.cloud import automl_v1beta1
from google.cloud.automl_v1beta1.proto import service_pb2

from oauth2client.client import GoogleCredentials
from google.oauth2 import service_account

import globals

class objectLabelingThread (threading.Thread):
    def __init__(self, threadID, name, q, qL):
        threading.Thread.__init__(self, group=None)
        self.threadID = threadID
        self.name = name
        self.weight = 0
        self.q = q
        self.qL = qL

        # filter warnings, load the configuration
        warnings.filterwarnings("ignore")
        self.conf = json.load(open('conf.json'))

        # initialize the AutoML API
        credentials = service_account.Credentials.from_service_account_file(r"/home/pi/creds.json")
        self.prediction_client = automl_v1beta1.PredictionServiceClient(credentials=credentials)
        self.modelName = 'projects/{}/locations/us-central1/models/{}'.format(self.conf['project_id'], self.conf['model_id'])

        # initialize the camera and grab a reference to the raw camera capture
        self.camera = PiCamera()
        self.camera.resolution = tuple(self.conf[ "resolution"])
        self.camera.framerate = self.conf[ "fps"]
        self.rawCapture = PiRGBArray(self.camera, size=tuple(self.conf[ "resolution"]))

        # allow the camera to warmup, then initialize the average frame, last
        # uploaded timestamp, and frame motion counter
        print self.name + "| warming up camera..."
        time.sleep(self.conf[ "camera_warmup_time"])
        self.avg = None
        self.lastUploaded = datetime.datetime.now()
        self.motionCounter = 0

        # stop event to terminate the thread 
        self.stopEvent = threading.Event()

        # init GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.conf['motion_led_pin'], GPIO.OUT)
    def stop(self):
        self.stopEvent.set()
    def run(self):
        print "Starting " + self.name
        self.processFrames()
        print "Exiting " + self.name
    def processFrames(self): 
        # capture frames from the camera
        for f in self.camera.capture_continuous(self.rawCapture, format="bgr", use_video_port=True):
            if self.stopEvent.is_set():
                break

            # grab the raw NumPy array representing the image and initialize
            # the timestamp and occupied/unoccupied text
            frameArr = f.array
            timestamp = datetime.datetime.now()
            motion = False

            # resize the frame, convert it to grayscale, and blur it
            frame = imutils.resize(frameArr, width=500)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            # if the average frame is None, initialize it
            if self.avg is None:
                print self.name + '|starting motion detection background model...'
                self.avg = gray.copy().astype("float")
                self.rawCapture.truncate(0)
                continue

            # accumulate the weighted average between the current frame and
            # previous frames, then compute the difference between the current
            # frame and running average
            cv2.accumulateWeighted(gray, self.avg, 0.5)
            frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(self.avg))

            # threshold the delta image, dilate the thresholded image to fill
            # in holes, then find contours on thresholded image
            thresh = cv2.threshold(frameDelta, self.conf[ "delta_thresh"], 255,
                cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)
            cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE)
            cnts = imutils.grab_contours(cnts)

            # loop over the contours
            for c in cnts:
                # if the contour is too small, ignore it
                if cv2.contourArea(c) < self.conf[ "min_area"]:
                    continue

                # compute the bounding box for the contour, draw it on the frame,
                # and update the text
                #(x, y, w, h) = cv2.boundingRect(c)
                #cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                motion = True

            # draw the text and timestamp on the frame
            #ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
            #cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                #0.35, (0, 0, 255), 1)

            # check to see if motion was detected
            if motion:
                # check to see if enough time has passed between uploads
                if (timestamp - self.lastUploaded).seconds >= self.conf[ "min_upload_seconds"]:
                    # increment the motion counter
                    self.motionCounter += 1

                    # check to see if the number of frames with consistent motion is
                    # high enough
                    if self.motionCounter >= self.conf[ "min_motion_frames"]:    
                        payload = {'image': {'image_bytes': cv2.imencode('.jpg', frameArr)[1].tostring() }}

                        print self.name + '|motion detected, querying AutoML...'
                        GPIO.output(self.conf['motion_led_pin'], GPIO.HIGH)

                        queryThread = threading.Thread(target = self.queryAutoML, args=(payload, timestamp))
                        queryThread.start()

                        # update the last uploaded timestamp and reset the motion
                        # counter
                        self.lastUploaded = timestamp
                        self.motionCounter = 0

            # otherwise, no motion was detected
            else:
                self.motionCounter = 0

            # check to see if the frames should be displayed to screen
            if self.conf[ "show_video"]:
                # display the security feed
                cv2.imshow("Food Buddy", frame)
                key = cv2.waitKey(1) & 0xFF

                # if the `q` key is pressed, break from the lop
                if key == ord("q"):
                    break

            # clear the stream in preparation for the next frame
            self.rawCapture.truncate(0)
    def queryAutoML(self, payload, timestamp):
        request = self.prediction_client.predict(self.modelName, payload, {})
        print globals.bcolors.OKBLUE + self.name + '|received response from AutoML API' + globals.bcolors.ENDC
        GPIO.output(self.conf['motion_led_pin'], GPIO.LOW)

        self.qL.acquire()
        try:
            self.q.put({
                "timestamp": timestamp, 
                "type": "object-detected", 
                "value": request.payload[0].display_name
            })
        except:
            print globals.bcolors.FAIL + ' error in getting object name from AutoML API' + globals.bcolors.ENDC
        self.qL.release()