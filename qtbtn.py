#!/usr/bin/python
#qtbtn.py
#Copyright 2012,2015 Elliot Wolk
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtQuick import *
from PyQt5.QtWidgets import *
from collections import deque

import dbus
import dbus.service
import dbus.mainloop.glib
import glob
import os
import re
import sys
import subprocess
import signal
import tempfile
import time

DEFAULT_ICON_DIR = "/usr/share/icons"
DEFAULT_ICON_THEME = "hicolor"
DEFAULT_ICON_MAX_WIDTH = 256
DEFAULT_INFOBAR_FONT_SIZE = 32

signal.signal(signal.SIGINT, signal.SIG_DFL)

DBUS_SERVICE_PREFIX = "org.teleshoes.qtbtn"

usage = """Usage:
  %(exec)s CONFIG_FILE

  OPTIONS:
    --landscape
      align top of UI with longest screen dimension
        if screen width < screen height:
          rotate UI 90 degrees clockwise
        else
          do not rotate UI
    --portrait
      align top of UI with shortest screen dimension
        if screen width > screen height:
          rotate UI 90 degrees clockwise
        else
          do not rotate UI

    --fullscreen | -f
      show window fullscreen (this is the default)
    --window | -w
      show regular, non-fullscreen window
    --size=WIDTHxHEIGHT
      set the window size, and the content size
      NOTE:
        this affects --landscape/--portrait determination

    --scale=SCALING_FACTOR
      set 'scale' property on main QML Item to SCALING_FACTOR,
        a real number with 1.0 for unscaled

    --center
      align widgets in the center (this is the default)
    --left
      align widgets on the left

    --bg | --run-in-background
      continue updating infobars when window is not active

    --dbus=SERVICE_SUFFIX
      instead of showing the window, listen for dbus signals controlling it
      also, do not quit app on window close
      service: "%(dbusServicePrefix)s.SERVICE_SUFFIX"
        SERVICE_SUFFIX may contain only lowercase letters a-z
        e.g.: %(dbusServicePrefix)s.powermenu
      path: "/"
      methods:
        show(): show the window
        hide(): hide the window
        quit(): quit the application
""" % {"exec": sys.argv[0], "dbusServicePrefix": DBUS_SERVICE_PREFIX}

def main():
  args = sys.argv
  args.pop(0)

  orientation=None
  fullscreen=True
  width=None
  height=None
  center=True
  useDbus=False
  dbusServiceSuffix=None
  runInBackground=False
  scale = 1.0
  while len(args) > 0 and args[0].startswith("-"):
    arg = args.pop(0)
    if arg == "--landscape":
      orientation = "landscape"
    elif arg == "--portrait":
      orientation = "portrait"
    elif arg == "--fullscreen" or arg == "-f":
      fullscreen=True
    elif arg == "--window" or arg == "-w":
      fullscreen=False
    elif RE.match("^--size=(\d+)x(\d+)$", arg):
      width = int(RE.group(1))
      height = int(RE.group(2))
    elif RE.match("^--scale=(\d+|\d*\.\d+)$", arg):
      scale = float(RE.group(1))
    elif arg == "--center":
      center = True
    elif arg == "--left":
      center = False
    elif arg == "--bg" or arg == "--run-in-background":
      runInBackground = True
    elif RE.match("--dbus=([a-z]+)", arg):
      dbusServiceSuffix = RE.group(1)
      useDbus = True
    else:
      sys.stderr.write(usage)
      sys.exit(2)

  if len(args) != 1:
    sys.stderr.write(usage)
    sys.exit(2)

  configFile = args[0]

  app = QApplication([])

  if width == None or height == None:
    geometry = app.desktop().availableGeometry()
    (width, height) = (geometry.width(), geometry.height())

  entries = Config(configFile).readConfFile()

  qml = QmlGenerator(width, height, scale, orientation, center, entries).getQml()
  fd, qmlFile = tempfile.mkstemp(prefix="qtbtn_", suffix=".qml")
  fh = open(qmlFile, 'w')
  fh.write(qml)
  fh.close()

  widget = MainWindow(qmlFile, entries, runInBackground)
  widget.resize(width, height)

  if useDbus:
    app.setQuitOnLastWindowClosed(False)
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    service = DBUS_SERVICE_PREFIX + "." + dbusServiceSuffix
    qtBtnDbus = qtBtnDbusFactory(service)
    if fullscreen:
      qtBtnDbus.signals.show.connect(widget.showFullScreen)
    else:
      qtBtnDbus.signals.show.connect(widget.show)
    qtBtnDbus.signals.hide.connect(widget.hide)
    qtBtnDbus.signals.quit.connect(QCoreApplication.instance().quit)
  else:
    if fullscreen:
      widget.showFullScreen()
    else:
      widget.show()

  app.exec_()

class DbusQtSignals(QObject):
  show = pyqtSignal()
  hide = pyqtSignal()
  quit = pyqtSignal()

def qtBtnDbusFactory(dbusService):
  class QtBtnDbus(dbus.service.Object):
    def __init__(self):
      dbus.service.Object.__init__(self, self.getBusName(), '/')
      self.signals = DbusQtSignals()
    def getBusName(self):
      return dbus.service.BusName(dbusService, bus=dbus.SessionBus())

    @dbus.service.method(dbusService)
    def show(self):
      print("show: " + dbusService)
      self.signals.show.emit()

    @dbus.service.method(dbusService)
    def hide(self):
      print("hide: " + dbusService)
      self.signals.hide.emit()

    @dbus.service.method(dbusService)
    def quit(self):
      print("quit: " + dbusService)
      self.signals.quit.emit()

  return QtBtnDbus()

class QmlGenerator():
  def __init__(self, width, height, scale, orientation, center, entries):
    self.entries = entries
    self.width = width
    self.height = height
    self.scale = scale
    self.orientation = orientation
    self.center = center
    self.landscapeMaxRowLen = 7
    self.portraitMaxRowLen = 4

  def getQml(self):
    qml = ""
    qml += self.indent(0, self.getHeader())
    qml += self.indent(1, self.getMain())
    qml += "\n"
    for entry in self.entries:
      if entry['entryType'] == "rowbreak":
        qml += "\n"
      elif entry['entryType'] == "colbreak":
        qml += "\n"
      elif entry['entryType'] == "infobar":
        qml += self.indent(1, self.getInfobar(entry))
      elif entry['entryType'] == "button":
        qml += self.indent(1, self.getButton(entry))
      else:
        raise ValueError("unknown entryType: " + str(entryType))
      qml += "\n"
    qml += self.indent(0, self.getFooter())
    return qml

  def indent(self, level, msg):
    lines = msg.splitlines()
    while len(lines) > 0 and len(lines[-1].strip(' ')) == 0:
      lines.pop()
    while len(lines) > 0 and len(lines[0].strip(' ')) == 0:
      lines.pop(0)
    minspaces = None
    for line in lines:
      if len(line.strip(' ')) == 0:
        continue
      spaces = len(line) - len(line.lstrip(' '))
      if minspaces == None:
        minspaces = spaces
      else:
        minspaces = min(spaces, minspaces)
    newlines = []
    for line in lines:
      newlines.append('  ' * level + line[minspaces:] + "\n")
    return ''.join(newlines)

  def getMain(self):
    if self.orientation == "landscape" and self.width < self.height:
      rotationDegrees = 90
    elif self.orientation == "portrait" and self.width > self.height:
      rotationDegrees = 90
    else:
      rotationDegrees = 0

    return self.getLayout(self.landscapeMaxRowLen, rotationDegrees)

  def getLayout(self, maxRowLen, rotationDegrees):
    gridCols = self.splitGrid(maxRowLen)
    if self.center:
      anchorFct = "centerIn"
    else:
      anchorFct = "fill"
    qml = ""
    qml += "Rectangle{\n"
    qml += "  width: " + str(self.width) + "\n"
    qml += "  height: " + str(self.height) + "\n"
    qml += "  rotation: " + str(rotationDegrees) + "\n"
    qml += "  Row{\n"
    qml += "    anchors." + anchorFct + ": parent\n"
    qml += "    spacing: 10\n"
    for colRows in gridCols:
      qmlRows = map(self.getRow, colRows)
      qml += "    Column{\n"
      qml += "      spacing: 10\n"
      qml +=        self.indent(3, "\n".join(qmlRows))
      qml += "    }\n"
    qml += "  }\n"
    qml += "}\n"
    print(qml)
    return qml

  def getRow(self, row):
    qml = ""
    qml += "Row{\n"
    qml += "  spacing: 10\n"
    for entry in row:
      qml += "  Loader { sourceComponent: " + entry['widgetId'] + " }\n"
    qml += "}"
    return qml

  def splitGrid(self, maxRowLen):
    gridCols = []
    curCol = None
    curRow = None
    for entry in self.entries:
      if curCol == None:
        curCol = []
        gridCols.append(curCol)

      if curRow == None:
        curRow = []
        curCol.append(curRow)

      if entry['entryType'] == "infobar":
        curCol.append([entry])
        curRow = None
      elif entry['entryType'] == "button":
        curRow.append(entry)
      elif entry['entryType'] == "rowbreak":
        curRow = None
      elif entry['entryType'] == "colbreak":
        curRow = None
        curCol = None

    return gridCols

  def getHeader(self):
    return """
      import QtQuick 2.3

      Rectangle {
        scale: %(scale)f;
   """ % {"scale": self.scale}
  def getFooter(self):
    return """
      }
    """

  def getInfobar(self, entry):
    return """
        Component{
          id: %(widgetId)s
          Text {
            property variant column: parent.parent.parent
            property string infobarWidgetId: "%(widgetId)s"
            objectName: "infobar"
            textFormat: Text.RichText
            font.pointSize: %(fontSize)s
            width: column.width
            clip: true
          }
        }
    """ % entry

  def getButton(self, entry):
    return """
      Component{
        id: %(widgetId)s
        Rectangle {
          border.color: "black"
          border.width: 5
          property variant hover: false
          property variant buttonColorDefault: "gray"
          property variant buttonColorClicked: "black"
          property variant buttonColorHover: "light gray"
          property variant buttonColorGradient: "white"

          property variant buttonColor: buttonColorDefault
          MouseArea {
            hoverEnabled: true
            anchors.fill: parent
            onClicked: commandRunner.runCommand("%(command)s")
            function setColor(){
              if(this.pressed){
                parent.buttonColor = parent.buttonColorClicked
              }else if(this.containsMouse){
                parent.buttonColor = parent.buttonColorHover
              }else{
                parent.buttonColor = parent.buttonColorDefault
              }
            }
            onEntered: setColor()
            onExited: setColor()
            onPressed: setColor()
            onReleased: setColor()
          }
          gradient: Gradient {
            GradientStop { position: 0.0; color: buttonColor }
            GradientStop { position: 1.0; color: buttonColorGradient }
          }

          Text {
            text: "%(name)s"
            font.pointSize: 20
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
          }
          Image {
            source: "%(icon)s"
            anchors.fill: parent
            anchors.topMargin: 10
            anchors.bottomMargin: 30
            anchors.leftMargin: 10
            anchors.rightMargin: 10
          }
          width: %(btnWidth)s
          height: %(btnHeight)s
        }
      }
    """ % entry


class CommandRunner(QObject):
  def __init__(self, mainWindow, entries, infobarWidgets, runInBackground):
    QObject.__init__(self, mainWindow)
    self.mainWindow = mainWindow
    self.entries = entries
    self.infobarWidgets = infobarWidgets
    self.runInBackground = runInBackground

    self.cmdsByWidgetId = {}
    for entry in entries:
      self.cmdsByWidgetId[entry["widgetId"]] = entry["command"]

    self.infobarsTimerIntervalMillis = 1000
    self.infobarsTimer = QTimer(self)
    self.infobarsTimer.timeout.connect(self.updateInfobars)
    self.setInfobarsTimerEnabled(True)
    if not self.runInBackground:
      self.mainWindow.activeChanged.connect(self.onMainWindowActiveChanged)
  @pyqtSlot(str)
  def runCommand(self, command):
    os.system(command)
    time.sleep(0.5)
    self.updateInfobars()
  def onMainWindowActiveChanged(self):
    self.setInfobarsTimerEnabled(self.mainWindow.isActive())
  def setInfobarsTimerEnabled(self, enabled):
    self.infobarsTimer.stop()
    if enabled:
      self.infobarsTimer.start(self.infobarsTimerIntervalMillis)
  def updateInfobars(self):
    if not self.runInBackground and not self.mainWindow.isActive():
      return

    for infobarWidget in self.infobarWidgets:
      widgetId = infobarWidget.property("infobarWidgetId")
      cmd = self.cmdsByWidgetId[widgetId]
      print("  running infobar command: " + cmd)

      try:
        proc = subprocess.Popen(['sh', '-c', cmd],
          stdout=subprocess.PIPE)
        msg = proc.stdout.read().decode(encoding="utf-8", errors="replace")
        msg = msg.strip()
        proc.terminate()
      except:
        msg = "ERROR"
      infobarWidget.setProperty("text", msg)

class MainWindow(QQuickView):
  def __init__(self, qmlFile, entries, runInBackground):
    super(MainWindow, self).__init__(None)
    self.setSource(QUrl(qmlFile))

    infobarWidgets = self.rootObject().findChildren(QObject, "infobar")
    self.commandRunner = CommandRunner(self, entries, infobarWidgets, runInBackground)
    self.commandRunner.updateInfobars()
    self.rootContext().setContextProperty("commandRunner", self.commandRunner)

class Config():
  def __init__(self, confFile):
    self.confFile = confFile
  def getEntry(self, number, entryType,
               name=None, icon=None, command=None,
               btnWidth=None, btnHeight=None, fontSize=None):
    if entryType == "rowbreak":
      widgetId = None
    elif entryType == "colbreak":
      widgetId = None
    elif entryType == "infobar":
      widgetId = "infobar" + str(number)
    elif entryType == "button":
      widgetId = "button" + str(number)
    else:
      raise ValueError("unknown entryType: " + str(entryType))
    return { "widgetId": widgetId
           , "name": name
           , "entryType": entryType
           , "icon": self.getIconPath(icon)
           , "command": command
           , "btnWidth": btnWidth
           , "btnHeight": btnHeight
           , "fontSize": fontSize
           }
  def getIconPath(self, icon):
    if icon == None:
      return ""

    if icon != None and os.path.isfile(icon):
      return os.path.abspath(icon)
    elif RE.match('\s*(\w+)\s*:\s*(.*)', icon):
      themeName = RE.group(1)
      iconName = RE.group(2)
      return self.findIcon(iconName,
        DEFAULT_ICON_DIR, themeName, DEFAULT_ICON_MAX_WIDTH)
    else:
      themeName = DEFAULT_ICON_THEME
      iconName = icon
      return self.findIcon(iconName,
        DEFAULT_ICON_DIR, themeName, DEFAULT_ICON_MAX_WIDTH)
  def findIcon(self, iconName, iconBaseDir, themeName, maxWidth):
    if iconName == None:
      return ""

    iconName = RE.sub('\.\w+$', '', iconName)
    iconName = iconName.lower()

    dirs = glob.glob(iconBaseDir + "/" + themeName + "/*x*/")
    for iconDir in dirs:
      if RE.match('/(\d+)x(\d)+/', iconDir):
        dirWidth = int(RE.group(1))
        dirHeight = int(RE.group(2))
        if dirWidth > maxWidth:
          next

      for root, dirs, files in os.walk(iconDir):
        for f in files:
          if RE.match('^' + iconName + '\.\w+$', f.lower()):
            return root + "/" + f

    return ""
  def readConfFile(self):
    if not os.path.exists(self.confFile):
      print >> sys.stderr, self.confFile + " is missing"
      sys.exit(1)
    cmds = []
    number = 0

    entries = []
    curEntry = None
    for line in open(self.confFile, "r").readlines():
      line = line.strip()
      if len(line) == 0:
        continue
      elif RE.match('^#', line):
        continue
      elif RE.match('^(.+)\\\\$', line):
        if curEntry == None:
          curEntry = ""
        curEntry += RE.group(1)
      else:
        if curEntry == None:
          curEntry = ""
        curEntry += line
        entries.append(curEntry)
        curEntry = None
    if curEntry != None:
      entries += curEntry

    for entry in entries:
      csv = entry.split(',', 5)
      if len(csv) == 1 and csv[0].strip() == "rowbreak":
        cmds.append(self.getEntry(number, entryType="rowbreak"))
      elif len(csv) == 1 and csv[0].strip() == "colbreak":
        cmds.append(self.getEntry(number, entryType="colbreak"))
      elif len(csv) == 2 and csv[0].strip() == "infobar":
        fontSize = DEFAULT_INFOBAR_FONT_SIZE
        command = csv[1].strip()
        cmds.append(self.getEntry(number, entryType="infobar", command=command,
          fontSize=fontSize))
        number+=1
      elif len(csv) == 3 and csv[0].strip() == "infobar":
        fontSize = csv[1].strip()
        command = csv[2].strip()
        cmds.append(self.getEntry(number, entryType="infobar", command=command,
          fontSize=fontSize))
        number+=1
      elif len(csv) == 5:
        name = csv[0].strip()
        btnWidth = csv[1].strip()
        btnHeight = csv[2].strip()
        icon = csv[3].strip()
        command = csv[4].strip()
        cmds.append(self.getEntry(number, entryType="button",
                    name=name, icon=icon, command=command,
                    btnWidth=btnWidth, btnHeight=btnHeight))
        number+=1
      elif len(csv) == 3:
        name = csv[0].strip()
        icon = csv[1].strip()
        command = csv[2].strip()
        btnWidth = 150
        btnHeight = 180
        cmds.append(self.getEntry(number, entryType="button",
                    name=name, icon=icon, command=command,
                    btnWidth=btnWidth, btnHeight=btnHeight))
        number+=1
      else:
        raise Exception("Error parsing config line: " + line)
    return cmds

#threadsafety: DANGEROUS AF
class RE:
  lastMatch = None

  @staticmethod
  def match(regex, s):
    RE.lastMatch = re.match(regex, s)
    return RE.lastMatch
  @staticmethod
  def sub(regex, repl, s):
    return re.sub(regex, repl, s)
  @staticmethod
  def group(num):
    return RE.lastMatch.group(num)

if __name__ == "__main__":
  sys.exit(main())
