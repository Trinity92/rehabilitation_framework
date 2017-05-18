#!/usr/bin/env python

from abc import ABCMeta, abstractmethod
import cv2
import signal
import numpy as np
import sys
import argparse
import roslib; roslib.load_manifest('reha_game')
import rospy
import rospkg
from std_msgs.msg import String
from os.path import expanduser
import os
import shlex
from subprocess import Popen,PIPE,STDOUT
from threading import Thread
from time import sleep

#                 |y=-0.1
#        D        |      A
#x=-0.1           |             x=0.1
#------------------------------------
#                 |
#       C         |      B
#                 |y=0.1


# some class definitions that represent enums
class Limb:
	LEFT_ARM, RIGHT_ARM, LEFT_LEG, RIGHT_LEG = range(4)
class RotationType:
	INTERNAL, EXTERNAL = range(2)
class MotionType:
	FLEXION, ABDUCTION = range(2)
class Color:
	YELLOW, BLUE, BLACK = range(3)

# returns the HSV thresholds of the color (as a tuple) passed as parameter
def get_hsv_thresholds(color):
	if color == Color.BLUE:
		# HSV color thresholds for BLUE
		THRESHOLD_LOW = np.array([110,50,50], dtype=np.uint8)
		THRESHOLD_HIGH = np.array([130,255,255], dtype=np.uint8)
	elif color == Color.BLACK:
		# HSV color thresholds for BLACK (not recommended for usage due to huge amounts of noise)
		THRESHOLD_LOW = np.array([60,15,0], dtype=np.uint8)
		THRESHOLD_HIGH = np.array([105,170,110], dtype=np.uint8)
	elif color == Color.YELLOW:
		# HSV color thresholds for YELLOW (default)
		THRESHOLD_LOW = np.array([15,210,20], dtype=np.uint8)
		THRESHOLD_HIGH = np.array([35,255,255], dtype=np.uint8)
	else:
		raise ValueError("Unknown or unused color!")
	return (THRESHOLD_LOW, THRESHOLD_HIGH)

# returns the correct Color type for a color's string representation, passed as a parameter
def string_to_color(color_str):
	if color_str == "yellow":
		return Color.YELLOW
	elif color_str == "blue":
		return Color.BLUE
	elif color_str == "black":
		return Color.BLACK
	else:
		raise ValueError("Cannot convert unrecognized string to color type!")

class VideoReader(Thread):
	def __init__(self, camera_resolution=(640,480), path_to_video="", color=Color.YELLOW):
		# Initialize camera and get actual resolution
		Thread.__init__(self)
                self.camera_resolution = camera_resolution
                self.path_to_video = path_to_video
                self.color = color
                self._center = None
                self._radius = 0
		self._kill_thread = False

	# ****************************** property definitions for the base class ******************************
	@property
	def img_original(self):
		return self._img_original

	@property
	def img_modified(self):
		return self._img_modified

	@property
	def center(self):
		return self._center

	@property
	def radius(self):
		return self._radius

	@property
	def path_to_video(self):
		return self._path_to_video
	@path_to_video.setter
	def path_to_video(self, path_to_video):
		# TODO: add more checks here! (f.ex. type checking)
		if path_to_video == "" or os.path.isfile(path_to_video):
			self._path_to_video = path_to_video
		else:
			raise ValueError("Specified video file does not exist!")

	@property
	def camera_resolution(self):
		return (self._camera_width, self._camera_height)
	@camera_resolution.setter
	def camera_resolution(self, camera_resolution):
		if not type(camera_resolution) is tuple or len(camera_resolution) != 2:
			raise TypeError("camera_resolution argument must be a tuple of two integers!")
		elif not all(type(x) is int for x in camera_resolution):
			raise TypeError("Tuple must only contain integers!")
		elif camera_resolution[0] not in [320,424,640,848,960,1280,1920] or camera_resolution[1] not in [180,240,360,480,540,720,1080]:
			raise ValueError("Invalid camera resolution!")
		else:	
			self._camera_width = camera_resolution[0]
			self._camera_height = camera_resolution[1]

	@property
	def color(self):
		return self._color
	@color.setter
	def color(self, color):
		if not (type(color) is int) or color not in range(3):
			raise TypeError("Invalid color!")
		else:	
			self._color = color
	# *****************************************************************************************************
	
	def set_kill_thread(self):
		self._kill_thread = True

	def run(self):
                # start capture device
		if self.path_to_video == "":
			self._cap = cv2.VideoCapture(0)
		else:
			self._cap = cv2.VideoCapture(self.path_to_video)

                # set camera width and height
		self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_resolution[0])
		self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_resolution[1])

		# check if camera/video file was opened successfully
		if not self._cap.isOpened():
			raise Exception("Failed to open video capture stream! Aborting...")
	
                # Minimum required radius of enclosing circle of contour
                MIN_RADIUS = 2

                # read frames from the capture device until interruption
                while not self._kill_thread:
                    rval, img_original = self._cap.read()
                    if not rval:
                            raise Exception("Failed to get frame from capture device!")
		    self._img_original = img_original.copy()

                    # Blur image to remove noise
                    img_modified = cv2.GaussianBlur(img_original.copy(), (3, 3), 0)

                    # Convert image from BGR to HSV
                    img_modified = cv2.cvtColor(img_modified, cv2.COLOR_BGR2HSV)

                    # Set pixels to white if in color range, others to black (binary bitmap)
                    hsv_thresholds = get_hsv_thresholds(self.color)
                    img_modified = cv2.inRange(img_modified, hsv_thresholds[0], hsv_thresholds[1])

                    # Dilate image to make white blobs larger
                    self._img_modified = cv2.dilate(img_modified, None, iterations = 1)

                    # Find center of object using contours instead of blob detection. From:
                    # http://www.pyimagesearch.com/2015/09/14/ball-tracking-with-opencv/
                    contours = cv2.findContours(self._img_modified, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
                    self._center = None
                    self._radius = 0
                    if len(contours) > 0:
                            c = max(contours, key=cv2.contourArea)
                            ((x, y), self._radius) = cv2.minEnclosingCircle(c)
                            M = cv2.moments(c)
                            if M["m00"] > 0:
                                    self._center = (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))
                                    if self._radius < MIN_RADIUS:
                                            self._center = None

                    #if center != None:
                            #moment = int(center[0]/(self.camera_resolution[0]/32))
                            #print moment
                            #if (moment < self._last_moment):
                            #	self._last_moment = moment
                            #	moment_status = -1
                            #elif (moment > self._last_moment):
                            #	self._last_moment = moment
                            #	moment_status = 1
                    #self._last_moment_status = moment_status
                                # draw a green circle around the largest enclosed contour

                    # draw circle arround the detected object and write number of repetitions done on frame
                    if self._center != None:
                            cv2.circle(self._img_original, self._center, int(round(self._radius)), np.array([0,255,0]))
                    #font = cv2.FONT_HERSHEY_SIMPLEX
                    #cv2.putText(img_original, "Repetitions: " + str(repetitions),(10,80), font, 1,(0,0,255),2)
    	# returns the latest frame that was retrieve by the capture device
    	def get_next_frame(self):
		if hasattr(self, "_frame"):
			return self._frame

class EncouragerUnit(object):
	repetitions = 0
	repetitions_limit = 0
	sentences = []
	ENC_SENT_FILELOC = "/config/encouragement_sentences.txt"

	def __init__(self, repetitions_limit=10, spawnRosNodes=False):
		if spawnRosNodes:
			# launch roscore, wm_voice_manager and soundplay
			self.roscore_node = Popen(['roscore'], stdout=None, stderr=None)
			sleep(0.2)
			self.soundplay_node = Popen(['rosrun', 'sound_play', 'soundplay_node.py'], stdout=None, stderr=None)
			self.wm_voice_generator_node = Popen(['rosrun', 'wm_voice_generator', 'wm_voice_component_short.py'], stdout=None, stderr=None)
		rospy.init_node('reha_game')
		self.pub = rospy.Publisher('/robot/voice', String)
		self.load_sentences()
		self.repetitions_limit = repetitions_limit

	def load_sentences(self):
		# retrieve path to reha_game ROS package and load sentences file
		rospack = rospkg.RosPack()
		reha_game_pkg_path = rospack.get_path('reha_game')
		sentences_file = open(reha_game_pkg_path + self.ENC_SENT_FILELOC, "r")
		self.sentences = sentences_file.readlines()
		sentences_file.close()

	def init_exercise(self, width=640, height=480):
		self.exercise_node = Popen(['rosrun', 'reha_game', 'Exercise1.py', '--width', str(width), '--height', str(height), '--calibrate'], stdout=PIPE, stderr=STDOUT)

	def stop_exercise(self):
		self.exercise_node.kill()
		self.exercise_node.wait()

	def inc_repetitions_counter(self):
		self.repetitions += 1
		self.pub.publish(str(self.repetitions))
		print "Current number of repetitions done: " +str(self.repetitions)
		if self.repetitions == self.repetitions_limit/2:
			self.pub.publish(self.sentences[0])
			print self.sentences[0]
		elif self.repetitions == self.repetitions_limit-1:
			self.pub.publish(self.sentences[1])
			print self.sentences[1]
		elif self.repetitions == self.repetitions_limit:
			self.pub.publish(self.sentences[2])
			print self.sentences[2]

	def say(self, sentence):
		self.pub.publish(sentence)
		print "The robot says: \"" + sentence + "\""


# implementation of a custom timer thread that simply counts seconds up to some defined limit
class Timer(Thread):
	def __init__(self, seconds=1):
		self.seconds = seconds
		Thread.__init__(self)
	def run(self):
		temp = (self.seconds*1.0)/100.0
		for i in xrange(1,100):
			sleep(temp)


# *************************************************************
# EXERCISE CLASSES: used to instantiate the different exercises
# *************************************************************

# base class for all Exercise classes
class Exercise:
	__metaclass__ = ABCMeta

	def __init__(self, repetitions_limit=10, calibration_duration=10, camera_resolution=(640,480), color=Color.YELLOW, argv=None, limb=Limb.LEFT_ARM, time_limit=0, path_to_video=""):
		self.repetitions_limit = repetitions_limit
		self.calibration_duration = calibration_duration
		if calibration_duration > 0:
			self._calibration_points = []
		self.camera_resolution = camera_resolution
		self.limb = limb
		self.time_limit = time_limit
		self._spawn_nodes = False
                self._video_reader = VideoReader(camera_resolution, path_to_video, color)
                self._video_reader.start()
		if argv != None:
			self.process_args(argv)
		self._encourager = EncouragerUnit(self.repetitions_limit, spawnRosNodes=self._spawn_nodes)
		sleep(0.2)	# wait some miliseconds until the video reader grabs its first frame from the capture device

		# define tolerance values for both axis, in case we're calibrating manually
		self._tolerance_x = camera_resolution[0] / 8
		self._tolerance_y = camera_resolution[1] / 8
		if camera_resolution[0] > 2*camera_resolution[1]:
			self._tolerance_x = camera_resolution[0] / 6
		elif 2*camera_resolution[0] < camera_resolution[1]:
			self._tolerance_y = camera_resolution[1] / 6

	# ****************************** property definitions for the base class ******************************
	@property
	def repetitions_limit(self):
		return self._repetitions_limit
	@repetitions_limit.setter
	def repetitions_limit(self, repetitions_limit):
		if repetitions_limit not in range(1,100):
			raise ValueError("repetitions_limit should be a positive integer value between 1 and 100!")
		else:
			self._repetitions_limit = repetitions_limit

	@property
	def calibration_duration(self):
		return self._calibration_duration
	@calibration_duration.setter
	def calibration_duration(self, calibration_duration):
		if not (type(calibration_duration) is int):
			raise TypeError("Integer value expected!")
		elif calibration_duration not in range(0,30):	# max. caibration duration: 30 seconds
			raise ValueError("calibration_duration should be an integer value between 0 and 30!")
		else:
			self._calibration_duration = calibration_duration


	@property
	def limb(self):
		return self._limb
	@limb.setter
	def limb(self, limb):
		if not (type(limb) is int) or limb not in range(4):
			raise TypeError("Invalid limb type!")
		else:
			self._limb = limb

	@property
	def time_limit(self):
		return self._time_limit
	@time_limit.setter
	def time_limit(self, time_limit):
		if not (type(time_limit) is int):
			raise TypeError("Integer value expected!")
		elif time_limit not in range(7200):	# max. time limit: 2 hours
			raise ValueError("time_limit should be an integer value between 0 and 7200!")
		else:
			self._time_limit = time_limit
	# *****************************************************************************************************

	# abstract method that calibrates the camera device with the necessary point coordinates needed for the exercise
	@abstractmethod
	def calibrate(self):
		raise NotImplementedError

	# base class method that starts the exercise
	def start_game(self):
		# check if capture device has been initialized and calibrated
		if not self._video_reader.is_alive():
			raise Exception("Capture device not initialized!")
		elif len(self._calibration_points) == 0:
			raise Exception("Device was not calibrated!")

		print "Camera dimensions: " +  str(cv2.CAP_PROP_FRAME_WIDTH) + " x " + str(cv2.CAP_PROP_FRAME_HEIGHT)
		print "Tolerance: " + str(self._tolerance_x) + " x " + str(self._tolerance_y) + " pixels"
		print "Press the \"q\" key to quit."

		# Main loop
		index=0
		while self._encourager.repetitions != self._encourager.repetitions_limit:
			# check if hand movement thresholds have been reached and count repetitions accordingly
			if self._video_reader.center != None :
				if abs(self._video_reader.center[0]-(self._calibration_points[index])[0]) < self._tolerance_x and abs(self._video_reader.center[1]-(self._calibration_points[index])[1]) < self._tolerance_y :
						index += 1
						if index == len(self._calibration_points):
							index = 0
							self._encourager.inc_repetitions_counter()
							
			# display images and quit loop if "q"-key was pressed
			cv2.imshow("Original image", self._video_reader.img_original)
			cv2.imshow("Detected blobs", self._video_reader.img_modified)
			if cv2.waitKey(1) & 0xFF == ord('q') or not self._video_reader.is_alive():
				self._video_reader.set_kill_thread()
				break
		cv2.destroyAllWindows()

	# method that processes the arguments given as a parameter
	def process_args(self, argv):
		if len(argv) > 0:
			parser = argparse.ArgumentParser(description='Reads video footage from a camera or a video file, and performs the Rehazenter exercise on it.')
			parser.add_argument('--width', type=int, dest="width", help='width of the camera window')
			parser.add_argument('--height', type=int, dest="height", help='height of the camera window')
			parser.add_argument('--path-to-video', type=str, dest="path_to_video", help='file path to the video file (default: webcam)')
			#parser.add_argument('--path-to-samples-folder', '-f', type=str, dest="arg_path_to_samples_folder", help='path to the folder where the object\'s image samples are stored')
			parser.add_argument('--color', type=str, dest="color", help='the color of the object that should be tracked (default=yellow)')
			parser.add_argument('--spawn_nodes', action="store_true", dest="spawn_nodes", help='pass this argument in order to launch all the needed ROS nodes, if they aren\'t running already')
			args = parser.parse_args(argv)
			self._video_reader.camera_resolution = (args.width, args.height)
			self._video_reader.color = string_to_color(args.color)
			if args.path_to_video != None:
				self._video_reader.path_to_video = args.path_to_video
			else:
				self._video_reader.path_to_video = ""
			self._spawn_nodes = args.spawn_nodes


# exercise that counts circular movements performed on the table surface
class RotationExercise(Exercise):
	def __init__(self, repetitions_limit=10, calibration_duration=10, camera_resolution=(640,480), color=Color.YELLOW, argv=None, limb=Limb.LEFT_ARM, time_limit=0, rotation_type=RotationType.INTERNAL):
		super(RotationExercise, self).__init__(repetitions_limit, calibration_duration, camera_resolution, color, argv, limb)
		self._rotation_type = rotation	

	@property
	def rotation_type(self):
		return self._rotation_type
	@rotation_type.setter
	def rotation_type(self, rotation_type):
		if not (type(rotation_type) is int) or (rotation_type not in range(2)):
			raise TypeError("Invalid rotation type!")
		else:
			self._rotation_type = rotation_type

	#def calibrate(self, calibration_points):
		# do stuff


# exercise that counts simple movements with 2 or 3 point coordinates performed on the table surface
class SimpleMotionExercise(Exercise):
	def __init__(self, repetitions_limit=10, calibration_duration=10, camera_resolution=(640,480), color=Color.YELLOW, argv=None, limb=Limb.LEFT_ARM, time_limit=0, motion_type=MotionType.FLEXION):
		super(SimpleMotionExercise, self).__init__(repetitions_limit, calibration_duration, camera_resolution, color, argv, limb)
		self._motion_type = motion_type

	@property
	def motion_type(self):
		return self._motion_type
	@motion_type.setter
	def motion_type(self, motion_type):
		if not (type(motion_type) is MotionType):
			raise TypeError("Invalid motion type!")
		else:
			self._motion_type = motion_type


	def calibrate(self):
		# check if capture device running
                if not (self._video_reader.is_alive()):
			raise Exception("Capture device not initialized!")

		# define number of calibration points to record (depends on exercise)
		number_of_calibration_points = 0
		if self.motion_type == MotionType.FLEXION or self.motion_type == MotionType.ABDUCTION:
			number_of_calibration_points = 2
		self._calibration_points = []

		# set this variable to whatever time you want (in seconds!)
		CALIBRATION_DURATION_SECS = 10

		# Main calibration loop
		timer = 0
		self._encourager.say("Calibrating now... please move your hand to the desired position on the table and hold for a few seconds.")
		while len(self._calibration_points) < number_of_calibration_points:
			# get next frame from capture device
			frame = self._video_reader.img_modified

			# (re-)initialize timer if necessary
			if timer == None or timer == 0:
				timer = Timer(CALIBRATION_DURATION_SECS)
				timer.start()
				if len(self._calibration_points) > 0:
					self._encourager.say("Now, move your arm to the next position and hold it for a few seconds.")

			# store coordinates when timer has run out
			if timer != None and timer.is_alive() == False:
				self._calibration_points.append(self._video_reader.center)
				del timer
				timer = None

			# display images and quit loop if "q"-key was pressed
			cv2.imshow("Original image", self._video_reader.img_original)
			cv2.imshow("Detected blobs", self._video_reader.img_modified)
			if cv2.waitKey(1) & 0xFF == ord('q') or not self._video_reader.is_alive():
				break
		self._encourager.say("Calibration completed! You may start your exercise now!")

#class ConesExercise(Exercise)



# ************************************************************************************
# *********************************** MAIN PROGRAM ***********************************
# ************************************************************************************
if __name__ == '__main__':
	# use the "rospy.myargv" argument vector instead of the built-in "sys.argv" to avoid problems with ROS argument re-mapping
	# (reason: https://groups.google.com/a/rethinkrobotics.com/forum/#!topic/brr-users/ErXVWhRmtNA)
	motion_ex = SimpleMotionExercise(argv=rospy.myargv()[1:])
	motion_ex.calibrate()
	motion_ex.start_game()
	sys.exit()