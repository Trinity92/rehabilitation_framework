#!/usr/bin/env python
# -*- coding: utf-8 -*)-

# Form implementation generated from reading ui file 'self.UI.ui'
#
# Created by: PyQt4 UI code generator 4.11.4
#
# WARNING! All changes made in this file will be lost!

from PyQt4 import QtCore, QtGui
from PyQt4.QtCore import QThread, QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt4.QtGui import QMessageBox, QFileDialog, QWidget, QTabWidget, QLabel, QImage, QPixmap, QGraphicsScene, QGraphicsPixmapItem, QHeaderView, QTableWidgetItem
import os,sys,inspect,ast
from subprocess import Popen
import rospy
import cv2
import MySQLdb
import numpy as np
from Crypto.Hash import SHA256
# include parent "src" directory to sys.path, otherwise import won't work
# (source: http://stackoverflow.com/questions/714063/importing-modules-from-parent-folder)
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
#print currentdir
parentdir = os.path.dirname(currentdir)
#print parentdir
sys.path.insert(0,parentdir)
from PyQt4 import uic
#from Exercises import Limb,RotationType,MotionType,RobotPosition
from rehabilitation_framework.msg import *
from std_msgs.msg import Bool,String
from sensor_msgs.msg import Image,CompressedImage
import DefineNewColor
from cv_bridge import CvBridge
import csv
from EncouragerUnit import EncouragerUnit
from Exercises import SimpleMotionExercise, RotationExercise

# some helper functions
def load_color_file(filename):
    rgb_color_fileptr = open(filename, "r")
    colors = []
    for line in rgb_color_fileptr.readlines():
        to_array = ast.literal_eval(line)
        assert len(to_array) == 3
        color = RGBColor()
        color.red = to_array[0]
        color.green = to_array[1]
        color.blue = to_array[2]
        colors.append(color)
    rgb_color_fileptr.close()
    return colors

def load_calib_file(filename):
    calib_fileptr = open(filename, "r")
    calibration_points_left_arm = []
    calibration_points_right_arm = []
    # TODO: add checks to see if the calibration data corresponds to current exercise settings
    for line in calib_fileptr.readlines():
        cb_points_from_file = []
        if line.startswith("calibration_points_left_arm="):
            cb_points_from_file = ast.literal_eval(line[28:])
            if len(cb_points_from_file) == 0:
                raise ValueError("Invalid file contents!")
        elif line.startswith("calibration_points_right_arm="):
            cb_points_from_file = ast.literal_eval(line[29:])
            if len(cb_points_from_file) == 0:
                raise ValueError("Invalid file contents!")
        if len(cb_points_from_file) > 0:
            for cb_point in cb_points_from_file:
                point_to_add = CalibrationPoint()
                point_to_add.x = cb_point[0]
                point_to_add.y = cb_point[1]
                if line.startswith("calibration_points_left_arm="):
                    calibration_points_left_arm.append(point_to_add)
                else:
                    calibration_points_right_arm.append(point_to_add)
    calib_fileptr.close()
    return (calibration_points_left_arm, calibration_points_right_arm)

@pyqtSlot(object, int)
def robot_finished_triggered(gui, status):
    # meaning of status:
    #	0: calibration reply, success
    #	1: calibration reply, interrupted/error
    #	2: exercise reply, success
    #	3: exercise reply, interrupted/error
    if status == 0:
        gui.msgErrorWarning.setText("Calibration successful! Data was written to specified filepath.")
        gui.msgErrorWarning.setWindowTitle("Calibration successful")
        gui.msgErrorWarning.exec_()
    elif status == 1:
        gui.msgErrorWarning.setText("Calibration was interrupted! Please try to calibrate again.")
        gui.msgErrorWarning.setWindowTitle("Calibration interrupted")
        gui.msgErrorWarning.exec_()
    elif status == 2:
        gui.msgErrorWarning.setText("Exercise was completed successfully! Results were written to .csv files.")
        gui.msgErrorWarning.setWindowTitle("Exercise successful")
        gui.msgErrorWarning.exec_()
    elif status == 3:
        gui.msgErrorWarning.setText("Exercise was interrupted! Please try again.")
        gui.msgErrorWarning.setWindowTitle("Exercise interrupted")
        gui.msgErrorWarning.exec_()
    gui.enableAllWidgets()

@pyqtSlot(object, QImage)
def img_received_triggered(gui, img):
    scene = QGraphicsScene()
    pixmap = QGraphicsPixmapItem(QPixmap(img), None, scene)
    gui.grOriginalImage.setScene(scene)
    gui.grOriginalImage.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
    
@pyqtSlot(object)
def smartcard_rosmsg_received_triggered(gui):
    gui.lblInsert.setEnabled(True)
    gui.lblInsert.setText("SmartCard detected! Please proceed below.")
    gui.lblAuth.setVisible(True)
    gui.lblAuth.setEnabled(True)
    gui.lblPINCode.setVisible(True)
    gui.lblPINCode.setEnabled(True)
    gui.lnPINCode.setVisible(True)
    gui.lnPINCode.setEnabled(True)
    gui.btnConfirm.setVisible(True)
    gui.btnConfirm.setEnabled(True)

@pyqtSlot(object)
def logoff_signal_received_triggered(gui):
    gui.lblInsert.setText("Please insert your smart card into the card reader to continue...")
    gui.lblAuth.setVisible(False)
    gui.lblPINCode.setVisible(False)
    gui.lnPINCode.setVisible(False)
    gui.btnConfirm.setVisible(False)
    gui.grProfilePicture.setVisible(False)
    gui.lblHelloMsg.setVisible(False)
    gui.lblRemove.setVisible(False)
    gui.lnPINCode.clear()
    gui.tabWidget.setTabEnabled(1, False)
    gui.tabWidget.setTabEnabled(2, False)
    gui.tabWidget.setTabEnabled(3, False)
    gui.tabWidget.setTabEnabled(4, False)


#------------------------

class QTRehaZenterGUI(QtGui.QMainWindow):
    robot_finished = pyqtSignal(object, int, name="robot_finished")
    img_received = pyqtSignal(object, QImage, name="img_received")
    smartcard_rosmsg_received = pyqtSignal(object, name="smartcard_rosmsg_received")
    logoff_signal_received = pyqtSignal(object, name="logoff_signal")
    _save_calib_filename = ""
    _encourager = EncouragerUnit()
    
    # MySQL login info
    mysql_hostname = "192.168.100.1"
    mysql_password = "qt_exercise_creator"
    mysql_user = "qt_exercise_creator"
    
    # information on the current user
    _rfid = "None"
    
    def __init__(self):
        super(QTRehaZenterGUI, self).__init__()
        uic.loadUi(currentdir + '/ui_files/QTRehaZenterGUI.ui', self)
        
        # connect to DB and create cursor object to perform queries
        self._mysqldb_connection = MySQLdb.connect(host=self.mysql_hostname, user=self.mysql_user, passwd=self.mysql_password, db="iot")
        
        # initialize custom object loader widget
        self.defineNewColorWidget = DefineNewColor.UIDefineNewColorWidget(self)

        # disable camera feed tab on startup (enabled later)
        self.tabWidget.setTabEnabled(2, False)
        
        # load logo images
        uniLuLogoScene = QGraphicsScene()
        imagePixmap_unilu = QGraphicsPixmapItem(QPixmap(QImage(currentdir + "/imgs/university_of_luxembourg_logo.png")), None, uniLuLogoScene)
        self.grUniLuLogo.setScene(uniLuLogoScene)
        self.grUniLuLogo.fitInView(uniLuLogoScene.sceneRect(), Qt.KeepAspectRatio)
        luxAILogoScene = QGraphicsScene()
        imagePixmap_luxai = QGraphicsPixmapItem(QPixmap(QImage(currentdir + "/imgs/luxai_logo.png")), None, luxAILogoScene)
        self.grLuxAILogo.setScene(luxAILogoScene)
        self.grLuxAILogo.fitInView(luxAILogoScene.sceneRect(), Qt.KeepAspectRatio)
        
        # initialize calibration file selection dialog
        self.dlgLoadCalibFile = QFileDialog()
        self.dlgLoadCalibFile.setFileMode(QFileDialog.ExistingFile)
        self.dlgLoadCalibFile.setFilter("Calibration files (*.clb)")
        self.dlgLoadCalibFile.setAcceptMode(QFileDialog.AcceptOpen)
        
        # initialize color file selection dialog
        self.dlgLoadColorFile = QFileDialog()
        self.dlgLoadColorFile.setFileMode(QFileDialog.ExistingFile)
        self.dlgLoadColorFile.setFilter("Color files (*.clr)")
        self.dlgLoadColorFile.setAcceptMode(QFileDialog.AcceptOpen)
        
        # initialize calibration file save dialog
        self.dlgSaveCalibFile = QFileDialog()
        self.dlgSaveCalibFile.setFileMode(QFileDialog.AnyFile)
        self.dlgSaveCalibFile.setFilter("Calibration files (*.clb)")
        self.dlgSaveCalibFile.setAcceptMode(QFileDialog.AcceptSave)
        
        # initialize rotation exercises warning message box
        self.msgRotationExercises = QMessageBox()
        self.msgRotationExercises.setIcon(QMessageBox.Warning)
        self.msgRotationExercises.setText("Sorry, rotation exercises have not been implemented yet!")
        self.msgRotationExercises.setInformativeText("Please choose one of the motion exercises instead until rotation exercises become available.")
        self.msgRotationExercises.setWindowTitle("Rotation exercises warning")
        self.msgRotationExercises.setStandardButtons(QMessageBox.Ok)
        
        # initialize calibration fail message box
        self.msgErrorWarning = QMessageBox()
        self.msgErrorWarning.setIcon(QMessageBox.Warning)
        self.msgErrorWarning.setStandardButtons(QMessageBox.Ok)
        
        # initialize list of faces (in string form)
        self._faces_list = ["sad", "happy", "crying", "neutral", "showing_smile", "surprise", "breathing_exercise", "breathing_exercise_nose", "smile", "happy_blinking", "calming_down", "random emotion"]
        self.cmbFaces.addItems(self._faces_list)
        
        # disable various labels and widgets on startup
        self.lblPerRepetitions1.setEnabled(False)
        self.lblPerRepetitions2.setEnabled(False)
        self.spnQuantEncRep.setEnabled(False)
        self.cmbQualiEnc.setEnabled(False)
        self.btnDeleteLine.setEnabled(False)
        self.spnFixedReps.setEnabled(False)
        self.spnFrequencyReps.setEnabled(False)
        self.btnAddLine.setEnabled(False)
        self.lblAuth.setVisible(False)
        self.lblPINCode.setVisible(False)
        self.lnPINCode.setVisible(False)
        self.btnConfirm.setVisible(False)
        self.lblHelloMsg.setVisible(False)
        self.lblRemove.setVisible(False)
        self.grProfilePicture.setVisible(True)
        self.tabWidget.setTabEnabled(1, False)
        self.tabWidget.setTabEnabled(2, False)
        self.tabWidget.setTabEnabled(3, False)
        self.tabWidget.setTabEnabled(4, False)
        self.lblWrongPINCode.setVisible(False)
        self.grProfilePicture.setVisible(False)
        
        # resize table columns to match their text size
        header = self.tblEmotionalFeedback.horizontalHeader()
        header.setResizeMode(0, QHeaderView.Stretch)
        header.setResizeMode(1, QHeaderView.Stretch)
        header.setResizeMode(2, QHeaderView.Stretch)
        
        # initialize ROS publisher topics
        rospy.init_node("reha_interface", anonymous=True)
        self._exercise_request_pub = rospy.Publisher("exercise_request", ExerciseRequest, queue_size=1)
        self._exercise_stop_pub = rospy.Publisher("exercise_stop", Bool, queue_size=1)
        self._calibration_request_pub = rospy.Publisher("calibration_request", CalibrationRequest, queue_size=1)
        rospy.Subscriber("exercise_reply", ExerciseReply, self._server_reply_callback)
        rospy.Subscriber("calibration_reply", CalibrationReply, self._server_reply_callback)
        rospy.Subscriber("/plain/image_modified/compressed", CompressedImage, self._img_received_callback)
        rospy.Subscriber("/user_logging/initial_key", String, self._smartcard_detected_callback)
        #self._decryption_node = None

	# initialize some other necessary variables
        self._is_calibrating = False
        self._is_exercise_running = False
        self._bridge = CvBridge()
        
        # connect functions to widgets
        self.btnInternalRotationExercise.clicked.connect(self.btnInternalRotationExerciseClicked)
        self.btnExternalRotationExercise.clicked.connect(self.btnExternalRotationExerciseClicked)
        self.btnAbductionMotionExercise.clicked.connect(self.btnAbductionMotionExerciseClicked)
        self.btnFlexionMotionExercise.clicked.connect(self.btnFlexionMotionExerciseClicked)
        self.btnBegin.clicked.connect(self.btnBeginClicked)
        self.btnStop.clicked.connect(self.btnStopClicked)
        self.btnDefineNewColor.clicked.connect(self.openDefineNewColorWidget)
        self.slNbrBlocks.valueChanged.connect(self.slNbrBlocksValueChanged)
        self.rdFixed.clicked.connect(self.rdFixedClicked)
        self.rdFrequency.clicked.connect(self.rdFrequencyClicked)
        self.btnAddLine.clicked.connect(self.btnAddLineClicked)
        self.cmbFaces.currentIndexChanged.connect(self.cmbFacesCurrentIndexChanged)
        self.actionQuit.triggered.connect(self.closeEvent)
        self.btnDeleteLine.clicked.connect(self.btnDeleteLineClicked)
        self.tblEmotionalFeedback.itemClicked.connect(self.tblEmotionalFeedbackItemClicked)
        self.chkQualitative.clicked.connect(self.chkQualitativeClicked)
        self.chkQuantitative.clicked.connect(self.chkQuantitativeClicked)
        self.btnLoadColorFile.clicked.connect(self.btnLoadColorFileClicked)
        self.btnLoadCalibFile.clicked.connect(self.btnLoadCalibFileClicked)
        self.btnCalibrateNow.clicked.connect(self.btnCalibrateNowClicked)
        self.robot_finished.connect(robot_finished_triggered)
        self.img_received.connect(img_received_triggered)
        self.smartcard_rosmsg_received.connect(smartcard_rosmsg_received_triggered)
        self.logoff_signal_received.connect(logoff_signal_received_triggered)
        self.btnConfirm.clicked.connect(self.btnConfirmClicked)
        self.lnPINCode.textChanged.connect(self.disableErrorLabelOnEdit)
    
    def __del__(self):
        _mysqldb_connection.close()
    
    # **** some helper functions specific to the class ****
    def disableAllWidgets(self):
        # disable all other buttons while the chosen exercise is running
        self.btnFlexionMotionExercise.setEnabled(False)
        self.btnAbductionMotionExercise.setEnabled(False)
        self.btnInternalRotationExercise.setEnabled(False)
        self.btnExternalRotationExercise.setEnabled(False)
        self.btnBegin.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.slNbrBlocks.setEnabled(False)
        self.spnNbrRepetitions.setEnabled(False)
        self.spnTimeLimit.setEnabled(False)
        self.chkQualitative.setEnabled(False)
        self.chkQuantitative.setEnabled(False)
        self.spnQuantEncRep.setEnabled(False)
        self.cmbQualiEnc.setEnabled(False)
        self.btnDeleteLine.setEnabled(False)
        self.rdFixed.setEnabled(False)
        self.rdFrequency.setEnabled(False)
        self.spnFixedReps.setEnabled(False)
        self.spnFrequencyReps.setEnabled(False)
        self.cmbFaces.setEnabled(False)
        self.btnAddLine.setEnabled(False)
        self.spnWidth.setEnabled(False)
        self.spnHeight.setEnabled(False)
        self.cmbRobotPosition.setEnabled(False)
        self.spnCalibDuration.setEnabled(False)
        self.btnLoadColorFile.setEnabled(False)
        self.btnDefineNewColor.setEnabled(False)
        self.btnLoadCalibFile.setEnabled(False)
        self.cmbCreateCalibFileFor.setEnabled(False)
        self.btnCalibrateNow.setEnabled(False)
        self.btnAddLine.setEnabled(False)
        self.lnPINCode.setEnabled(False)
        self.tabWidget.setTabEnabled(2, True)

    def enableAllWidgets(self):
        # enable all other widgets
        self.btnFlexionMotionExercise.setEnabled(True)
        self.btnAbductionMotionExercise.setEnabled(True)
        self.btnInternalRotationExercise.setEnabled(True)
        self.btnExternalRotationExercise.setEnabled(True)
        self.btnBegin.setEnabled(False)
        self.btnStop.setEnabled(False)
        self.slNbrBlocks.setEnabled(True)
        self.spnNbrRepetitions.setEnabled(True)
        self.spnTimeLimit.setEnabled(True)
        self.chkQualitative.setEnabled(True)
        self.chkQuantitative.setEnabled(True)
        if self.chkQualitative.isChecked():
            self.cmbQualiEnc.setEnabled(True)
        else:    
            self.cmbQualiEnc.setEnabled(False)
        if self.chkQuantitative.isChecked():
            self.spnQuantEncRep.setEnabled(True)
        else:
            self.spnQuantEncRep.setEnabled(False)
        if self.tblEmotionalFeedback.rowCount() > 0:
            self.btnDeleteLine.setEnabled(True)
        else:
            self.btnDeleteLine.setEnabled(False)
        self.rdFixed.setEnabled(True)
        self.rdFrequency.setEnabled(True)
        self.spnFixedReps.setEnabled(False)
        self.spnFrequencyReps.setEnabled(False)
        self.btnAddLine.setEnabled(False)
        self.cmbFaces.setEnabled(True)
        self.btnAddLine.setEnabled(True)
        self.spnWidth.setEnabled(True)
        self.spnHeight.setEnabled(True)
        self.cmbRobotPosition.setEnabled(True)
        self.spnCalibDuration.setEnabled(True)
        self.btnLoadColorFile.setEnabled(True)
        self.btnDefineNewColor.setEnabled(True)
        self.btnLoadCalibFile.setEnabled(True)
        self.cmbCreateCalibFileFor.setEnabled(True)
        if self.lnColorFile.text() != "":
            self.btnCalibrateNow.setEnabled(True)
        else:
            self.btnCalibrateNow.setEnabled(False)
        self.lblPerRepetitions1.setEnabled(False)
        self.lblPerRepetitions2.setEnabled(False)
        self.tabWidget.setTabEnabled(2, False)
    
    # *******************************************************************************************
    # *************************  connector functions for the UI buttons  ************************
    # *******************************************************************************************
    def btnFlexionMotionExerciseClicked(self):
        # enable all other buttons except the one for exercise 1
        self.btnBegin.setEnabled(True)
        self.btnFlexionMotionExercise.setEnabled(False)
        self.btnAbductionMotionExercise.setEnabled(True)
        self.btnInternalRotationExercise.setEnabled(True)
        self.btnExternalRotationExercise.setEnabled(True)
        self.txtViewLogOutput.appendPlainText("Flexion motion exercise selected.")
    
    def btnAbductionMotionExerciseClicked(self):
        # enable all other buttons except the one for exercise 2
        self.btnBegin.setEnabled(True)
        self.btnFlexionMotionExercise.setEnabled(True)
        self.btnAbductionMotionExercise.setEnabled(False)
        self.btnInternalRotationExercise.setEnabled(True)
        self.btnExternalRotationExercise.setEnabled(True)
        self.txtViewLogOutput.appendPlainText("Abduction motion exercise selected.")
    
    def btnInternalRotationExerciseClicked(self):
        # enable all other buttons except the one for exercise 3
        self.btnBegin.setEnabled(True)
        self.btnFlexionMotionExercise.setEnabled(True)
        self.btnAbductionMotionExercise.setEnabled(True)
        self.btnInternalRotationExercise.setEnabled(False)
        self.btnExternalRotationExercise.setEnabled(True)
        self.txtViewLogOutput.appendPlainText("Internal rotation exercise selected.")
    
    def btnExternalRotationExerciseClicked(self):
        # enable all other buttons except the one for exercise 4
        self.btnBegin.setEnabled(True)
        self.btnFlexionMotionExercise.setEnabled(True)
        self.btnAbductionMotionExercise.setEnabled(True)
        self.btnInternalRotationExercise.setEnabled(True)
        self.btnExternalRotationExercise.setEnabled(False)
        self.txtViewLogOutput.appendPlainText("External rotation exercise selected.")
    
    def btnBeginClicked(self):
        # check various conditions before proceeding
        if self.btnAbductionMotionExercise.isEnabled() and self.btnFlexionMotionExercise.isEnabled() and self.btnInternalRotationExercise.isEnabled() and self.btnExternalRotationExercise.isEnabled():
            self.msgErrorWarning.setText("Please select an exercise type using one of the buttons above before proceeding.")
            self.msgErrorWarning.setWindowTitle("No exercise selected")
            self.msgErrorWarning.exec_()
            return
        elif not self.btnInternalRotationExercise.isEnabled() or not self.btnExternalRotationExercise.isEnabled():
            self.msgRotationExercises.exec_()
            return
        elif self.lnColorFile.text() == "":
            self.msgErrorWarning.setText("Please select a color file in the \"Calibration preferences\" tab before proceeding.")
            self.msgErrorWarning.setWindowTitle("No color file selected")
            self.msgErrorWarning.exec_()
            return
        elif self.lnCalibFile.text() == "":
            self.msgErrorWarning.setText("Please select a calibration file in the \"Calibration preferences\" tab before proceeding.")
            self.msgErrorWarning.setWindowTitle("No calibration file selected")
            self.msgErrorWarning.exec_()
            return
        self._is_calibrating = False
        self.txtViewLogOutput.appendPlainText("******************** BEGIN EXERCISE ********************")
        msg = ExerciseRequest()
        if not self.btnFlexionMotionExercise.isEnabled():
            msg.motion_type = 1
            msg.rotation_type = 0
        elif not self.btnAbductionMotionExercise.isEnabled():
            msg.motion_type = 2
            msg.rotation_type = 0
        
        # build exercise init message
        msg.camera_width = self.spnWidth.value()
        msg.camera_height = self.spnHeight.value()
        msg.blocks = self.slNbrBlocks.value()
        msg.time_limit = self.spnTimeLimit.value()
        msg.repetitions = self.spnNbrRepetitions.value()
        msg.calibration_duration = self.spnCalibDuration.value()
        if self.chkQuantitative.isChecked():
            msg.quantitative_frequency = self.spnQuantEncRep.value()
        else:
            msg.quantitative_frequency = 0
        if self.chkQualitative.isChecked():
            if self.cmbQualiEnc.currentText() == "high":
                msg.qualitative_frequency = 3
            else:
                msg.qualitative_frequency = 6
        else:
            msg.qualitative_frequency = 0
        msg.robot_position = self.cmbRobotPosition.currentIndex()
        msg.rotation_type = 0
        msg.emotional_feedback_list = []
        if self.tblEmotionalFeedback.rowCount() > 0:
            for i in range(0,self.tblEmotionalFeedback.columnCount()-1):
                if self.tblEmotionalFeedback.item(i, 0) != None:
                    emotional_feedback = EmotionalFeedback()
                    emotional_feedback.is_fixed_feedback = (str(self.tblEmotionalFeedback.item(i, 0).text()) == "fixed")
                    emotional_feedback.repetitions = int(self.tblEmotionalFeedback.item(i, 1).text())
                    emotional_feedback.face_to_show = str(self.tblEmotionalFeedback.item(i, 2).text())
                    gesture_item_text = self.tblEmotionalFeedback.item(i, 3).text()
                    if gesture_item_text == "Yes":
                        emotional_feedback.show_gesture = True
                    else:
                        emotional_feedback.show_gesture = False
                    msg.emotional_feedback_list.append(emotional_feedback)
        # show error dialog if files fail to load
        try:
            msg.rgb_colors = load_color_file(str(self.lnColorFile.text()))
        except ValueError:
            self.msgErrorWarning.setText("The specified color file has invalid contents!")
            self.msgErrorWarning.setWindowTitle("Invalid color file")
            self.msgErrorWarning.exec_()
            return
        except IOError:
            self.msgErrorWarning.setText("The specified color file could not be read! (does it exist?)")
            self.msgErrorWarning.setWindowTitle("Could not read color file")
            self.msgErrorWarning.exec_()
            return
        try:
            calib_data = load_calib_file(str(self.lnCalibFile.text()))
        except ValueError:
            self.msgErrorWarning.setText("The specified calibration file has invalid contents!")
            self.msgErrorWarning.setWindowTitle("Invalid calibration file")
            self.msgErrorWarning.exec_()
            return
        except IOError:
            self.msgErrorWarning.setText("The specified calibration file could not be read! (does it exist?)")
            self.msgErrorWarning.setWindowTitle("Could not read calibration file")
            self.msgErrorWarning.exec_()
            return
        msg.calibration_points_left_arm = calib_data[0]
        msg.calibration_points_right_arm = calib_data[1]
        self._exercise_request_pub.publish(msg)
        self.txtViewLogOutput.appendPlainText("Current exercise configuration:\n" + str(msg))
        self.disableAllWidgets()
        self._is_calibrating = False

    def btnStopClicked(self):
        # stop exercise on robot
        self._exercise_stop_pub.publish(self._is_calibrating)
        self._is_calibrating = False
        self._is_exercise_running = False

        # enable all other buttons again
        self.enableAllWidgets()
        if self._is_calibrating:
            self.txtViewLogOutput.appendPlainText("******************** END CALIBRATION *******************")
        else:
            self.txtViewLogOutput.appendPlainText("********************* END EXERCISE *********************")
        self.tabWidget.setTabEnabled(2, False)

    def chkQuantitativeClicked(self):
        self.spnQuantEncRep.setEnabled(self.chkQuantitative.isChecked())

    def chkQualitativeClicked(self):
        self.cmbQualiEnc.setEnabled(self.chkQualitative.isChecked())
         
    def btnLoadColorFileClicked(self):
        if self.dlgLoadColorFile.exec_():
            filename = self.dlgLoadColorFile.selectedFiles()[0]
            self.lnColorFile.setText(filename)
         
    def btnLoadCalibFileClicked(self):
        if self.dlgLoadCalibFile.exec_():
            filename = self.dlgLoadCalibFile.selectedFiles()[0]
            self.lnCalibFile.setText(filename)
         
    def rdFixedClicked(self):
        self.spnFrequencyReps.setEnabled(False)
        self.spnFixedReps.setEnabled(True)
        if self.cmbFaces.currentIndex() > -1:
            self.btnAddLine.setEnabled(True)
        else:
            self.btnAddLine.setEnabled(False)
     
    def rdFrequencyClicked(self):
        self.spnFrequencyReps.setEnabled(True)
        self.spnFixedReps.setEnabled(False)
        if self.cmbFaces.currentIndex() > -1:
            self.btnAddLine.setEnabled(True)
        else:
            self.btnAddLine.setEnabled(False)
     
    def btnDeleteLineClicked(self):
        self.tblEmotionalFeedback.removeRow(self.tblEmotionalFeedback.currentRow())
        self.btnDeleteLine.setEnabled(False)
     
    def btnCalibrateNowClicked(self):
        if self.lnColorFile.text() == "":
            self.msgErrorWarning.setText("Please select a color file in the \"Calibration preferences\" tab before proceeding.")
            self.msgErrorWarning.setWindowTitle("No color file selected")
            self.msgErrorWarning.exec_()
            return
        if self.dlgSaveCalibFile.exec_():
        # create calibration service request message
            self._is_calibrating = True
            request = CalibrationRequest()
            if str(self.cmbCreateCalibFileFor.currentText()) == "flexion exercise":
                request.motion_type = 1
                request.rotation_type = 0
            elif str(self.cmbCreateCalibFileFor.currentText()) == "abduction exercise":
                request.motion_type = 2
                request.rotation_type = 0
            else:
                self.msgRotationExercises.exec_()
                return
            try:
                request.rgb_color_list = load_color_file(str(self.lnColorFile.text()))
            except ValueError:
                self.msgErrorWarning.setText("The specified color file has invalid contents!")
                self.msgErrorWarning.setWindowTitle("Invalid color file")
                self.msgErrorWarning.exec_()
                return
            except IOError:
                self.msgErrorWarning.setText("The specified color file could not be read! (does it exist?)")
                self.msgErrorWarning.setWindowTitle("Could not read color file")
                self.msgErrorWarning.exec_()
                return
            request.robot_position = self.cmbRobotPosition.currentIndex()
            request.calibration_duration = self.spnCalibDuration.value()
            request.camera_width = self.spnWidth.value()
            request.camera_height = self.spnHeight.value()
            self._save_calib_filename = self.dlgSaveCalibFile.selectedFiles()[0]

            # publish request to topic
            self._last_calib_request_msg = request
            self.disableAllWidgets()
            self.tabWidget.setCurrentIndex(1)
            self._calibration_request_pub.publish(request)
            self.txtViewLogOutput.appendPlainText("******************* BEGIN CALIBRATION ******************")
            self.txtViewLogOutput.appendPlainText("Current calibration configuration:\n" + str(request))

    def tblEmotionalFeedbackItemClicked(self):
        self.btnDeleteLine.setEnabled(True)

    def btnAddLineClicked(self):
        self.tblEmotionalFeedback.insertRow(self.tblEmotionalFeedback.rowCount())
        if self.rdFixed.isChecked():
            typeText = "fixed"
            repetitionsText = str(self.spnFixedReps.value())
        elif self.rdFrequency.isChecked():
            typeText = "frequency"
            repetitionsText = str(self.spnFrequencyReps.value())
        else:
            raise Exception("error when selecting facial feedback, this is not supposed to happen...")
        faceText = self.cmbFaces.currentText()
        self.tblEmotionalFeedback.setItem(self.tblEmotionalFeedback.rowCount()-1, 0, QTableWidgetItem(typeText))
        self.tblEmotionalFeedback.setItem(self.tblEmotionalFeedback.rowCount()-1, 1, QTableWidgetItem(repetitionsText))
        self.tblEmotionalFeedback.setItem(self.tblEmotionalFeedback.rowCount()-1, 2, QTableWidgetItem(faceText))
        if self.chkShowGesture.isChecked():
            self.tblEmotionalFeedback.setItem(self.tblEmotionalFeedback.rowCount()-1, 3, QTableWidgetItem("Yes"))
        else:
            self.tblEmotionalFeedback.setItem(self.tblEmotionalFeedback.rowCount()-1, 3, QTableWidgetItem("No"))
        self.spnFixedReps.setEnabled(False)
        self.spnFrequencyReps.setEnabled(False)
        self.rdFixed.setChecked(False)
        self.rdFrequency.setChecked(False)
        self.cmbFaces.setCurrentIndex(-1)
        self.btnAddLine.setEnabled(False)

    def appendToTextView(self, line):
        self.txtViewLogOutput.appendPlainText(line)
         
    def cmbFacesCurrentIndexChanged(self):
        if self.rdFixed.isChecked() or self.rdFrequency.isChecked():
            self.btnAddLine.setEnabled(True)
         
    def openDefineNewColorWidget(self):
        self.defineNewColorWidget.show()
         
    def updateColorFileName(self, color_filename):
        self.lnColorFile.setText(color_filename)
         
    def slNbrBlocksValueChanged(self):
        self.lblNbrBlocksValue.setText(str(self.slNbrBlocks.value()))
         
    def closeEvent(self, event):
        reply = QtGui.QMessageBox.question(self, 'Message', "Are you sure that you want to quit?", QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            # stop anything that might still be running on the robot
            if self._is_exercise_running or self._is_calibrating:
                self._exercise_stop_pub.publish(self._is_calibrating)
            event.accept()
        else:
            event.ignore()

    def _server_reply_callback(self, data):
        # meaning of status:
        #	0: calibration reply, success
        #	1: calibration reply, interrupted/error
        #	2: exercise reply, success
        #	3: exercise reply, interrupted/error
        if data.status == 0:
            self._is_calibrating = False
            # write calibration points to file
            if not self._save_calib_filename.endsWith(".clb"):
                self._save_calib_filename += ".clb"
            calib_fileptr = open(currentdir + "/" + self._save_calib_filename, "w")
            if str(self.cmbCreateCalibFileFor.currentText()) == "flexion exercise":
                calib_fileptr.write("motion_type=1\n")
                calib_fileptr.write("rotation_type=0\n")
            elif str(self.cmbCreateCalibFileFor.currentText()) == "abduction exercise":
                calib_fileptr.write("motion_type=2\n")
                calib_fileptr.write("rotation_type=0\n")
            calib_fileptr.write("robot_position=" + str(self.cmbRobotPosition.currentIndex()) + "\n")
            calib_fileptr.write("calibration_points_left_arm=")
            str_to_write = "["
            for point in data.calibration_points_left_arm:
                str_to_write += "(" + str(point.x) + "," + str(point.y) + "),"
            calib_fileptr.write(str_to_write[:-1] + "]\n")
            calib_fileptr.write("calibration_points_right_arm=")
            str_to_write = "["
            for point in data.calibration_points_right_arm:
                str_to_write += "(" + str(point.x) + "," + str(point.y) + "),"
            calib_fileptr.write(str_to_write[:-1] + "]\n")
            calib_fileptr.close()
        elif data.status == 2:
            self._is_exercise_running = False
            #process exercise results message
            with open(currentdir + "/time_results.csv", "w") as csvfile:
                time_res_writer = csv.writer(csvfile, delimiter="\t")
                for res in data.time_results:
                        time_res_writer.writerow(res.data)
            with open(currentdir + "/repetitions_results.csv", "w") as csvfile:
                repetition_res_writer = csv.writer(csvfile, delimiter="\t")
                for res in data.repetitions_results:
                        repetition_res_writer.writerow([res])
            with open(currentdir + "/trajectory_smoothness_results.csv", "w") as csvfile:
                ts_res_writer = csv.writer(csvfile, delimiter="\t")
                for res in data.trajectory_smoothness_results:
                        ts_res_writer.writerow([res])
        self.robot_finished.emit(self, data.status)

    def _img_received_callback(self, data):
        # CompressedImage ROS messages are incompatible with cv2.bridge, conversion to numpy array and THEN to cv2 format possible however
        #cv_image = self._bridge.imgmsg_to_cv2(data, desired_encoding="rgb8")
        
        np_arr = np.fromstring(data.data, np.uint8)
        cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        
        height, width, byte_value = cv_image.shape
        byte_value = byte_value * width
        img = QImage(cv_image, width, height, byte_value, QImage.Format_RGB888)
        self.img_received.emit(self, img)

    def _smartcard_detected_callback(self, data):
        #print("Card detected!")
        # check if monitoring ROS node has detected a smartcard
        msg = str(data.data).replace(" ", "")
        if msg != "None" and self._rfid == "None":
            self._rfid = msg
            # just in case the user inserts another smart card before logoff is triggered...
            if self._rfid != msg:
		self.logoff_signal_received.emit(self)
            self.smartcard_rosmsg_received.emit(self)
        else:
            if self._rfid != "None" and msg == "None":
                self._rfid = "None"
                # kill decryption node
                #self._decryption_node.terminate()
                #self._decryption_node.wait()
                self.logoff_signal_received.emit(self)
                self._encourager.say("Good bye!")
                self._encourager.show_emotion("smile")

    def btnConfirmClicked(self):
        # check if PIN code corresponds to PIN code stored in database (use SHA-256 to hash passwords!)
        cursor = self._mysqldb_connection.cursor()
        query_str = "select * from tblUser where userID='" + self._rfid + "'"
        cursor.execute(query_str)
        if cursor.rowcount != 1:
            self.lblWrongPINCode.setVisible(True)
            cursor.close()
            return
        # fetch (only) matching row from DB
        tblUser_row = cursor.fetchone()
        # hash pin entered by user with salt string from DB
        pincode_hash = SHA256.new(str(self.lnPINCode.text()) + str(tblUser_row[4])).hexdigest().upper()
        #print pincode_hash
        if pincode_hash == tblUser_row[3]:
            # permit access to user and enable widgets accordingly
            self.lblWrongPINCode.setVisible(False)
            self.tabWidget.setTabEnabled(1, True)
            self.tabWidget.setTabEnabled(2, True)
            self.tabWidget.setTabEnabled(3, True)
            self.tabWidget.setTabEnabled(4, True)
            self.lblAuth.setEnabled(False)
            self.lblPINCode.setEnabled(False)
            self.lnPINCode.setEnabled(False)
            self.btnConfirm.setEnabled(False)
            self.lblHelloMsg.setVisible(True)
            self.lblHelloMsg.setText("Welcome back, " + tblUser_row[2] + "!")
            self.lblRemove.setVisible(True)
            self.grProfilePicture.setVisible(True)
            self.grProfilePicture.setEnabled(True)
            scene = QGraphicsScene()
            qimg = QtGui.QImage.fromData(tblUser_row[6])
            pixmap = QGraphicsPixmapItem(QPixmap.fromImage(qimg), None, scene)
            self.grProfilePicture.setScene(scene)
            self.grProfilePicture.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
            self.grProfilePicture.setVisible(True)
            self._encourager.say("Welcome back, " + tblUser_row[2] + "!")
            self._encourager.show_emotion("happy")
            ### HARDCODED: display different information depending on user connected ###
            if self._rfid == "3BEA00008131FE450031C573C0014000900077":
                self.slNbrBlocks.setValue(3)
                self.spnNbrRepetitions.setValue(25)
                self.chkQualitative.setChecked(False)
                self.chkQuantitative.setChecked(True)
                self.spnQuantEncRep.setEnabled(True)
                self.cmbQualiEnc.setEnabled(False)
                self.spnQuantEncRep.setValue(3)
            else:
                self.slNbrBlocks.setValue(2)
                self.spnNbrRepetitions.setValue(15)
                self.chkQualitative.setChecked(True)
                self.chkQuantitative.setChecked(True)
                self.spnQuantEncRep.setEnabled(True)
                self.spnQuantEncRep.setValue(2)
                self.cmbQualiEnc.setEnabled(True)
                self.cmbQualiEnc.setCurrentIndex(1)
  
            #launch_params = ['roslaunch', 'simple_image_cyphering', 'one_node_decryption.launch']
            #self._decryption_node = Popen(launch_params)
        else:
            self.lblWrongPINCode.setVisible(True)
        cursor.close()

    def disableErrorLabelOnEdit(self):
        self.lblWrongPINCode.setVisible(False)


# *******************************************************************************************
         
if __name__ == "__main__":
    from xmlrpclib import ServerProxy
    try:
        m = ServerProxy(os.environ['ROS_MASTER_URI'])
        code, msg, val = m.getSystemState("reha_interface")
    except:
        print("Unable to communicate with ROS master! Aborting.")
        sys.exit()
    app = QtGui.QApplication(sys.argv)
    myapp = QTRehaZenterGUI()
    #app.processEvents()
    myapp.show()
    sys.exit(app.exec_())
