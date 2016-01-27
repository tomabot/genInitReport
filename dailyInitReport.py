#!/usr/bin/python

#
# dailyInitReport.py
#
#    This script generates initialization reports. The command line options
#    are as follows:
#
#        --instr=cctXXX         the cell ct hostname (currently cct032 and cct034)
#        --logdir=<abspath>     the absolute path to the root of the log file directory
#        --rptdir=<abspath>     the absolute path to the root of the report directory
#                               
#    The results are stored as a pdf file in the location specified under rptdir in 
#    a subdirectory named by_date. There is an additional subdirectory under rptdir
#    named by_bcode with a hard link to the pdf file in the by_date subdirectory. 
#    This provides two separate filesystem entities that sort by date and by barcode
#    in the subdirectories by_date and by_bcode respectively. 

import string
import sys
import mmap
import os
import contextlib
import time
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as pyplot

from datetime import date, timedelta
from optparse import OptionParser

NumericMonth = { 
	"Jan":"01", "Feb":"02", "Mar":"03", "Apr":"04", "May":"05", "Jun":"06",
	"Jul":"07", "Aug":"08", "Sep":"09", "Oct":"10", "Nov":"11", "Dec":"12" }

class BarcodeData:
	def __init__( self, mm, tagIndex ): 
		categoryKeyword = "specimencategory="
		disposableKeyword = "disposable="

		# get the index to the log entry containing "spe specimen"
		speIndex = mm.find( "spe specimen", tagIndex )
		if( speIndex == -1 ):
			raise ValueError( "Can't locate specimen log entry" )
	
		keywordIndex = mm.find( categoryKeyword, mm.find( "\n", speIndex ))
		if( keywordIndex == -1 ):
			raise ValueError( "Can't determine specimen type" )

		categoryIndex = keywordIndex + len( categoryKeyword )
		self._category = mm[ categoryIndex : mm.find (" ", categoryIndex )]

		keywordIndex = mm.find( disposableKeyword, mm.find( "\n", speIndex ))
		if( keywordIndex == -1 ):
			raise ValueError( "Can't locate barcode" )

		bcodeIndex = keywordIndex + len( disposableKeyword )
		self._barcode = mm[ bcodeIndex : mm.find( " ", bcodeIndex )]
		self._dtStamp = DateTimeStamp( mm, bcodeIndex ) 

	def GetReport( self ):
		rptString = "Barcode(" + self._barcode + "), Specimen type(" + self._category + "), " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		return rptString

	def Barcode( self ):
		return self._barcode

class CapillaryCalibration:
	def __init__( self, config, mm, startIndex ):
		capcalString = "mode=capcal"
		successString = "status=success"
		fifteenMinString = "Fifteen minute"
		userStopString = ":USER: Stop"

		self._mm = mm
		self._index = startIndex
		self._capillaryCalibrationPassed = False
		self._config = config

		userStopIndex = mm.find( userStopString, startIndex )
		fifteenMinIndex = mm.find( fifteenMinString, startIndex )
		index = startIndex

		while( True ):

			capcalIndex = mm.find( capcalString, index )
			if( capcalIndex != -1 ):

				# there's a capcalString ("mode=capcal") in the file

				if( userStopIndex == -1 ):
					# there's no :USER: Stop in the file
					capcalFinishedBeforeUserStop = True

				elif( capcalIndex < userStopIndex ):
					# there's a :USER: Stop in the file somewhere
					# after the capillary calibration result
					capcalFinishedBeforeUserStop = True

				else:
					# there's a :USER: Stop in the file and it
					# happened before the capillary calibration finished
					capcalFinishedBeforeUserStop = False

				if( fifteenMinIndex == -1 ):
					# there's no 15 minute timeout in the file
					capcalFinishedBeforeFifteenMin = True

				elif( capcalIndex < fifteenMinIndex ):
					# there's a 15 minute timeout in the file and it
					# happened after the capillary calibration finished
					capcalFinishedBeforeFifteenMin = True

				else:
					# there's a 15 minute timeout in the file, and it
					# happened before the capillary calibration finished
					capcalFinishedBeforeFifteenMin = False


				# see if the capillary calibration finished before a 
				# :USER: Stop and before a fifteen minute timeout
				if( capcalFinishedBeforeUserStop and capcalFinishedBeforeFifteenMin ):

					# capillary calibration finished before a :USER: Stop and 
					# a 15 minute timeout
					resultIndex = capcalIndex + len( capcalString )

					# see if the capillary calibration succeeded in this log file
					successIndex = mm.find( successString, index )
					if( successIndex != -1 ):
						# capillary calibration succeeded
						self._dtStamp = DateTimeStamp( mm, successIndex ) 
						self._index = successIndex
						self._capillaryCalibrationPassed = True
						return

					else:
						# capillary calibration was not successful, 
						# advance to next test result
						index = resultIndex
						self._index = resultIndex
						continue

			# a capcal ~String ("mode=capcal") was not found in the file

			if( userStopIndex != -1 ):
				# found :USER: Stop
				self._dtStamp = DateTimeStamp( mm, userStopIndex )
				self._index = userStopIndex
				self._capillaryCalibrationPassed = False
				return

			if( fifteenMinIndex != -1 ):
				# 15 minute timeout occurred
				self._dtStamp = DateTimeStamp( mm, fifteenMinIndex )
				self._index = fifteenMinIndex
				self._capillaryCalibrationPassed = False
				return

			# there's no capcal string ("mode=capcal"), 
			# there's no a :USER: Stop, and there's no
			# fifteen minute time out in the file, get 
			# the next file... if there is a next file

			nextFileName = self.GetNextFilename( mm )
			if( nextFileName == "" ):

				# there is no n3d entry in the log file,
				# the ucm must have stopped suddenly

				self._dtStamp = DateTimeStamp( ) 
				self._capillaryCalibrationPassed = False
				return

			# open the next log file, and map it
			try:
				f = open( nextFileName, 'r' )
			except IOError as detail:
				filenotfound = 'file not found:' + os.path.basename(nextFileName)
				raise ValueError(filenotfound)
			
			mm = mmap.mmap( f.fileno(), 0, access=mmap.ACCESS_READ )
			self._mm = mm

			index = 0
			userStopIndex = mm.find( userStopString, 0 )
			fifteenMinIndex = mm.find( fifteenMinString, 0 )

	def GetNextFilename( self, mm ):
		n3dSearchStr = ":n3d "

		nextFileNameIndex = mm.rfind( n3dSearchStr )
		if( nextFileNameIndex == -1 ):
			return ""

		nextFileName = mm[ nextFileNameIndex + len( n3dSearchStr ) : mm.find( "\n", nextFileNameIndex )].strip()
		return self._config.LogDir( ) + '/' + nextFileName + '.log'

	def GetMMap( self ):
		return self._mm

	def GetIndex( self ):
		return self._index

	def GetReport( self ):
		rptString = ""
		if( self._capillaryCalibrationPassed == True ):
			rptString = "(pass)  Capillary Calibration " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		else:
			rptString = "(fail)  Capillary Calibration"
		return rptString

class DataCollection:
	def __init__( self, config, mm, startIndex ):

		pseString= ":pse "
		fifteenMinString = "Fifteen minute"
		userStopString = ":USER: Stop"

		self._mm = mm
		self._index = startIndex
		self._dataCollectionStarted = False
		self._config = config

		userStopIndex = mm.find( userStopString, startIndex )
		fifteenMinIndex = mm.find( fifteenMinString, startIndex )
		index = startIndex 

		while( True ):

			pseIndex = mm.find( pseString, index )
			if( pseIndex != -1 ):

				# data collection string found

				if( userStopIndex == -1 ):
					# there's no :USER: Stop in the file
					dataCollectionStartedBeforeUserStop = True

				elif( pseIndex < userStopIndex ):
					# there's a :USER: Stop in the file, and
					# data collection started before user stop
					dataCollectionStartedBeforeUserStop = True

				else:
					# there's a :USER: Stop in the file, and 
					# data collection started after user stop
					dataCollectionStartedBeforeUserStop = False

				if( fifteenMinIndex == -1 ):
					# there's no 15 minute timeout in the file
					dataCollectionStartedBeforeFifteenMin = True

				elif( pseIndex < fifteenMinIndex ):
					# there's a 15 minute timeout in the file, and 
					# data collection started before fifteen minute timeout
					dataCollectionStartedBeforeFifteenMin = True

				else:
					# there's a 15 minute timeout in the file, and 
					# data collection started after fifteen minute timeout
					dataCollectionStartedBeforeFifteenMin = False
			
				# see if data collection started before a :USER: Stop 
				# and before a fifteen minute timeout
				if( dataCollectionStartedBeforeUserStop and dataCollectionStartedBeforeFifteenMin ):
					self._dtStamp = DateTimeStamp( mm, pseIndex ) 
					self._dataCollectionStarted = True
					return

			if( userStopIndex != -1 ):
				# found :USER: Stop
				self._dtStamp = DateTimeStamp( mm, userStopIndex ) 
				self._index = userStopIndex
				self._dataCollectionStarted = False
				return

			if( fifteenMinIndex != -1 ):
				# 15 minute timeout occurred 
				self._dtStamp = DateTimeStamp( mm, fifteenMinIndex ) 
				self._index = fifteenMinIndex
				self._dataCollectionStarted = False
				return

			nextFileName = self.GetNextFilename( mm )
			if( nextFileName == "" ):

				# there is no n3d entry in the log file
				# the ucm must have stopped suddenly

				self._dtStamp = DateTimeStamp( )
				self._pressureVelocityTestPassed = False
				return

			# open the next log file, and map it
			try:
				f = open( nextFileName, 'r' ) 
			except IOError as detail:
				filenotfound = 'file not found:' + os.path.basename(nextFileName)
				raise IOError(filenotfound)
	
			mm = mmap.mmap( f.fileno(), 0, access=mmap.ACCESS_READ )
			self._mm = mm

			index = 0
			userStopIndex = mm.find( userStopString, 0 )
			fifteenMinIndex = mm.find( fifteenMinString, 0 )

	def GetNextFilename( self, mm ):
		n3dSearchStr = ":n3d "

		nextFileNameIndex = mm.rfind( n3dSearchStr )
		if( nextFileNameIndex == -1 ):
			return ""

		nextFileName = mm[ nextFileNameIndex + len( n3dSearchStr ) : mm.find( "\n", nextFileNameIndex )].strip()
		return self._config.LogDir( ) + '/' + nextFileName + '.log'

	def GetMMap( self ):
		return self._mm

	def GetReport( self ):
		rptString = ""
		if( self._dataCollectionStarted == True ):
			rptString = "(pass)  Data Collection Initiated " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		else:
			rptString  = "(fail)  Data Collection Aborted" # + self._dtStamp._rundate + " " + self._dtStamp._runtime
		return rptString

class DateTimeStamp:
	def __init__( self, mm = None, index = 0 ):
		if(( mm == None ) and ( index == 0 )):
			self._rundate = ""
			self._runtime = ""
			return 

		# get the index to the beginning of the line 
		lineIndex = mm.rfind( "\n", 0, index )
		if( lineIndex == -1 ):
			raise ValueError( "Can't locate beginning of the line" )

		# Break the line into words. The first two words are
		# 3 letter month and 0 suppressed day. Change to mm/dd/yyyy.
		lineField = mm[ lineIndex : index ].split()
		reportYear = lineField[ 5 ][ 7:11 ]
		self._rundate = NumericMonth[ lineField[ 0 ]] + "/" + lineField[ 1 ].zfill(2) + "/" + reportYear

		# the next field is the time stamp of when the sample
		# was processed. Just use the hh:mm:ss
		self._runtime = lineField[ 2 ][ 0:8 ] 

class FindCapillary:
	def __init__( self, mm, tagIndex ):
		manualFindString = ":USER: Coarse Focus Control  RESET" 
		manualFindIndex = tagIndex
		self._method = "automatic"

		# get the index for all of the ":cap is" 
		# values starting from the user-tag, and searching
		# to the end of the file
		absyList = self.getAbsYList( mm, tagIndex )

		# if the difference between the values of any two entries 
		# in the list is greater than 50 and less than 70, then 
		# the capillary was found automatically
		self._capillaryFound = self.capillaryWasFoundAutomatically( absyList )
		if( self._capillaryFound == True ):
			return	# capillary was found automatically

		# the capillary was not found automatically, 
		# see if it was found manually
		manualFindIndex = mm.find( manualFindString, manualFindIndex )

		while( True ):
			if( manualFindIndex > -1 ):
				# capillary was found manually
				self._capillaryFound = True
				self._method = "manual"
				return

			# manualFindString was not found in this file,
			# get the next file... if there is a next file
			nextFileName = self.GetNextFilename( mm )
			if( nextFileName == "" ):
				# there is no n3d entry in the log file,
				# the ucm must have stopped suddenly
				self._dtStamp = DateTimeStamp( ) 
				self._capillaryFound = False
				return

			# open the next log file, and map it
			try:
				f = open( nextFileName, 'r' )
			except IOError as detail:
				filenotfound = 'file not found:' + os.path.basename(nextFileName)
				raise ValueError(filenotfound)
			
			mm = mmap.mmap( f.fileno(), 0, access=mmap.ACCESS_READ )
			self._mm = mm

			manualFindIndex = mm.find( manualFindString, 0 )

	def capillaryWasFoundAutomatically( self, absyList ):
		if( len( absyList ) < 2 ):
			return False

		while( len( absyList ) > 1 ):
			absyValue = absyList.pop()
			for absy in absyList:
				absyDiff = abs( absyValue - absy )
				if(( absyDiff > 50.0 ) and ( absyDiff < 70.0 )):
					return True
		return False
		
	def getAbsYList( self, mm, index ):
		absyString = "absY=["
		capisString = ":cap is"

		absyList = []	
		absyIndex = mm.find( capisString, index )

		self._dtStamp = DateTimeStamp( mm, index ) 
		while( absyIndex != -1 ):
			absyIndex = mm.find( absyString, absyIndex )
			if( absyIndex == -1 ):
				break

			self._dtStamp = DateTimeStamp( mm, absyIndex ) 
			if( mm[ absyIndex + len( absyString )] != "]" ):
				lbracketIndex = absyIndex + len( absyString ) - 1
				rbracketIndex = mm.find( "]", lbracketIndex )

				tmpList = mm[ lbracketIndex + 1 : rbracketIndex ].split()
				for absyValue in tmpList:
					absyList.append( float( absyValue ))

			absyIndex = mm.find( capisString, absyIndex )
		return absyList

	def GetReport( self ):
		rptString = ""
		if( self._capillaryFound == True ):
			rptString = "(pass)  Find Capillary (" + self._method + ") " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		else:
			rptString = "(fail)  Find Capillary " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		return rptString

	def GetNextFilename( self, mm ):
		n3dSearchStr = ":n3d "

		nextFileNameIndex = mm.rfind( n3dSearchStr )
		if( nextFileNameIndex == -1 ):
			return ""

		nextFileName = mm[ nextFileNameIndex + len( n3dSearchStr ) : mm.find( "\n", nextFileNameIndex )].strip()
		return self._config.LogDir( ) + '/' + nextFileName + '.log'

class IlluminationCameraCalibration:
	def __init__( self, mm, tagIndex ):
		illumCalString = ":cal success"
		illumCalIndex = tagIndex

		self._illuminationCalibrationPassed = False
		self._cameraCalibrationPassed = False

		# get the index to the log entry containing ":cal success"
		illumCalIndex = mm.find( illumCalString, illumCalIndex )
		if( illumCalIndex == -1 ):
			self._dtStamp = DateTimeStamp( mm, tagIndex ) 
			return

		self._dtStamp = DateTimeStamp( mm, illumCalIndex ) 
		self._illuminationCalibrationPassed = True
		self._cameraCalibrationPassed = True

	def GetIllumReport( self ):
		rptString = ""
		if(( self._illuminationCalibrationPassed == True ) and ( self._cameraCalibrationPassed )):
			rptString = "(pass)  Illumination Calibration " + self._dtStamp._rundate + " " + self._dtStamp._runtime 
		else:
			rptString = "(fail)  Illumination Calibration " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		return rptString

	def GetCameraReport( self ):
		rptString = ""
		if(( self._illuminationCalibrationPassed == True ) and ( self._cameraCalibrationPassed )):
			rptString = "(pass)  Camera Calibration " + self._dtStamp._rundate + " " + self._dtStamp._runtime 
		else:
			rptString = "(fail)  Camera Calibration " + self._dtStamp._rundate + " " + self._dtStamp._runtime 
		return rptString

class PressureVelocityTest:
	def __init__( self, config, mm, startIndex ):

		pvString = "Pressure/PumpPos Slope"
		fifteenMinString = "Fifteen minute"
		userStopString = ":USER: Stop"

		self._mm = mm
		self._index = startIndex
		self._pressureVelocityTestPassed = False
		self._config = config

		userStopIndex = mm.find( userStopString, startIndex )
		fifteenMinIndex = mm.find( fifteenMinString, startIndex )
		index = startIndex 

		while( True ):

			pvIndex = mm.find( pvString, index )
			if( pvIndex != -1 ):

				# there's a "Pressure/PumpPos Slope" in the file

				if( userStopIndex == -1 ):
					# there's no :USER: Stop in the file
					pvTestFinishedBeforeUserStop = True

				elif( pvIndex < userStopIndex ):
					# there's a :USER: Stop in the file, somewhere 
					# after the PV test result
					pvTestFinishedBeforeUserStop = True

				else:
					# there's a :USER: Stop in the file, and it
					# happened before the PV test finished
					pvTestFinishedBeforeUserStop = False

				if( fifteenMinIndex == -1 ):
					# there's no 15 minute timeout in the file
					pvTestFinishedBeforeFifteenMin = True

				elif( pvIndex < fifteenMinIndex ):
					# there's a 15 minute timeout in the file, and it
					# happened after the PV test 
					pvTestFinishedBeforeFifteenMin = True

				else:
					# there's a 15 minute timeout in the file, and it
					# happened before the PV test 
					pvTestFinishedBeforeFifteenMin = False
			
				# see if the pv test finished before a :USER: Stop 
				# and before a fifteen minute timeout
				if( pvTestFinishedBeforeUserStop and pvTestFinishedBeforeFifteenMin ):

					# pv test finished before a :USER: Stop and a 15 minute 
					# timeout get the index to the string immediately following 
					# "Pressure/PumpPos Slope"

					resultIndex = pvIndex + len( pvString )
					resultStr = mm[ resultIndex : mm.find( "\n", resultIndex )]
					self._dtStamp = DateTimeStamp( mm, resultIndex ) 

					# see if the test was successful
					if(( resultStr != "NaN" ) and ( float( resultStr ) >= 0.0 )):
						# test was successful
						self._pressureVelocityTestPassed = True
						return

					else:
						# test was not successful, advance to next test result
						index = resultIndex
						continue

			if( userStopIndex != -1 ):
				# found :USER: Stop
				self._dtStamp = DateTimeStamp( mm, userStopIndex ) 
				self._mm = mm
				self._index = userStopIndex
				self._pressureVelocityTestPassed = False
				return

			if( fifteenMinIndex != -1 ):
				# 15 minute timeout occurred 
				#self._dtStamp = DateTimeStamp( mm, fifteenMinIndex ) 
				self._mm = mm
				self._index = fifteenMinIndex
				self._pressureVelocityTestPassed = False
				return

			nextFileName = self.GetNextFilename( mm )
			if( nextFileName == "" ):
				# there is no n3d entry in the log file
				self._dtStamp = DateTimeStamp( )
				self._pressureVelocityTestPassed= False
				return

			# open the next log file, and map it
			f = open( nextFileName, 'r' ) 
			mm = mmap.mmap( f.fileno(), 0, access=mmap.ACCESS_READ )
			self._mm = mm

			index = 0
			userStopIndex = mm.find( userStopString, 0 )
			fifteenMinIndex = mm.find( fifteenMinString, 0 )

	def GetNextFilename( self, mm ):
		n3dSearchStr = ":n3d "

		nextFileNameIndex = mm.rfind( n3dSearchStr )
		if( nextFileNameIndex == -1 ):
			return ""

		nextFileName = mm[ nextFileNameIndex + len( n3dSearchStr ) : mm.find( "\n", nextFileNameIndex )].strip()
		return self._config.LogDir( ) + '/' + nextFileName + '.log'

	def GetMMap( self ):
		return self._mm

	def GetIndex( self ):
		return self._index

	def GetReport( self ):
		rptString = ""
		if( self._pressureVelocityTestPassed == True ):
			rptString = "(pass)  Pressure/Velocity test " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		else:
			rptString = "(fail)  Pressure/Velocity test " + self._dtStamp._rundate + " " + self._dtStamp._runtime
		return rptString

class ReportHeader:
	def __init__( self, instr ):
		self._instr = instr
		self._reportTime = time.strftime("%H:%M:%S")
		self._reportDate = time.strftime("%m/%d/%Y")
	def GetReport( self ):
		return "Report Date: " + self._reportDate + "\n" \
			+  "Report Time: " + self._reportTime + "\n" \
			+  "Instrument:  " + self._instr

class RunTimeConfig:
	def __init__( self ):
		parser = OptionParser()
		parser.add_option( "-i", "--instr", dest="instr", help="instrument id" )
		parser.add_option( "-d", "--logdate", dest="logdate", help="log date" )
		parser.add_option( "-l", "--logdir", dest="logdir", help="log file directory" )
		parser.add_option( "-r", "--rptdir", dest="rptdir", help="report directory" )

		(options, args) = parser.parse_args()

		# handle instrument argument
		if options.instr == None:
			raise RuntimeError( "missing argument (instr)" )
		self._instr = options.instr

		# handle log date argument
		yesterday = date.today() - timedelta(1)
		yyyy = yesterday.strftime('%Y')
		mm = yesterday.strftime('%m')
		dd = yesterday.strftime('%d')

		if options.logdate != None:
			mm = options.logdate[0:2]
			dd = options.logdate[3:5]
			yyyy = options.logdate[6:]

		# handle log directory (input)
		if options.logdir != None:
			self._logdir = options.logdir 
		else:
			self._logdir = '/mnt/lancer/upload/DailyInstrumentData/' + self._instr + '/gservlog/ucm_logs/' + self._instr + '_' + yyyy + mm + '/' + dd 

		# handle report directory (output)
		if options.rptdir != None:
			self._rptdir = options.rptdir
		else:
			self._rptdir = '/mnt/lancer/upload/DailyInstrumentData/' + self._instr + '/reports'

	def LogDir( self ):
		return self._logdir

	def RptDir( self ):
		return self._rptdir

	def GetInstr( self ):
		return self._instr

def GetRptInfoFromFname( logFname ):
	bname = string.split( logFname, '.' )
	return string.split( bname, '_' )

def ProcessLogFile( logFname, config ):
	fullPathLogFname = config.LogDir( ) + "/" + logFname
	with open( fullPathLogFname, 'r' ) as f:
		try:
			mm = mmap.mmap( f.fileno(), 0, access=mmap.ACCESS_READ )
			loc = []
			loc.append( mm.rfind( ':USER: Start', 0 ))
			loc.append( mm.rfind( ':USER: Restart', 0 ))
			loc.append( mm.rfind( ':USER: Run', 0 ))
			userStartIndex = max( loc )

			if( userStartIndex > -1 ):
				fig = pyplot.figure( 1, figsize=(8.5, 11), dpi=100, facecolor='w' )
				fig.clear()

				rptTitle = "VisionGate CCT QC Report"
				print "\n", rptTitle
				fig.text( 0.10, 0.88, rptTitle,  ha='left', va='top' )

				rptHeadings = ReportHeader( config.GetInstr( ))
				print rptHeadings.GetReport()
				fig.text( 0.10, 0.84, rptHeadings.GetReport(), ha='left', va='top' )

				barcodeData = BarcodeData( mm, userStartIndex )
				print barcodeData.GetReport()
				fig.text( 0.10, 0.79, barcodeData.GetReport(), ha='left', va='top' )

				print '\nProcesses:'
				fig.text( 0.10, 0.75, 'Processes:', ha='left', va='top' )

				findCapillary = FindCapillary( mm, userStartIndex )
				print findCapillary.GetReport()
				fig.text( 0.14, 0.72, findCapillary.GetReport(), ha='left', va='top' )

				illumCamCalib = IlluminationCameraCalibration( mm, userStartIndex )
				print illumCamCalib.GetIllumReport()
				print illumCamCalib.GetCameraReport()
				fig.text( 0.14, 0.70, illumCamCalib.GetIllumReport(), ha='left', va='top' )
				fig.text( 0.14, 0.68, illumCamCalib.GetCameraReport(), ha='left', va='top' )

				pvTest = PressureVelocityTest( config, mm, userStartIndex )
				print pvTest.GetReport()
				fig.text( 0.14, 0.66, pvTest.GetReport(), ha='left', va='top' )

				# locating the capillary calibration status involves
				# following some number of log files, which involves
				# closing one memory map, and opening another
				capCal = CapillaryCalibration( config, pvTest.GetMMap(), pvTest.GetIndex())
				print capCal.GetReport()
				fig.text( 0.14, 0.64, capCal.GetReport(), ha='left', va='top' )

				# locating the data collection started information
				# also involves following some number of log files
				dataCol = DataCollection( config, capCal.GetMMap( ), capCal.GetIndex())
				print dataCol.GetReport()
				fig.text( 0.14, 0.62, dataCol.GetReport(), ha='left', va='top' )

				# save the report with a filename that sorts by data collection date
				nameByDate = string.split( logFname, '.' )[0] + '_' + barcodeData.Barcode()
				if(( findCapillary._capillaryFound == True ) and
					( illumCamCalib._illuminationCalibrationPassed == True ) and
					( pvTest._pressureVelocityTestPassed == True ) and
					( capCal._capillaryCalibrationPassed == True ) and
					( dataCol._dataCollectionStarted == True )):
					ccode = 'p'
				else:
					ccode = 'f'

				fullPathByDate = config.RptDir( ) + '/by_date/' + nameByDate + '_' + ccode + '.pdf'
				fig.savefig( fullPathByDate, format='pdf' )

				# save a hard link to the report file, and give the hard link a name that sorts on barcode
				nameByBcode = barcodeData.Barcode( ) + '_' + string.split( logFname, '.' )[0] 
				fullPathByBcode = config.RptDir( ) + '/by_bcode/' + nameByBcode + '_' + ccode + '.pdf'
				os.link( fullPathByDate, fullPathByBcode )

		except ValueError as detail:
			print "Incomplete report generated: ", detail

		try:
			mm.close()
		except UnboundLocalError as detail:
			print "Error closing log file: ", detail

# execution starts here
config = RunTimeConfig( )
logdir = config.LogDir( )

for fname in os.listdir( logdir ):
	ProcessLogFile( fname, config )

print "EOF"
