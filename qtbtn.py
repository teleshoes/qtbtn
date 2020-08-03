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

    --center
      align widgets in the center (this is the default)
    --left
      align widgets on the left

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
    elif RE.match("--size=(\d+)x(\d+)", arg):
      width = int(RE.group(1))
      height = int(RE.group(2))
    elif arg == "--center":
      center = True
    elif arg == "--left":
      center = False
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

  qml = QmlGenerator(width, height, orientation, center, entries).getQml()
  fd, qmlFile = tempfile.mkstemp(prefix="qtbtn_", suffix=".qml")
  fh = open(qmlFile, 'w')
  fh.write(qml)
  fh.close()

  widget = MainWindow(qmlFile, entries)
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
  def __init__(self, width, height, orientation, center, entries):
    self.entries = entries
    self.width = width
    self.height = height
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
      if entry['rowbreak']:
        qml += "\n"
      elif entry['infobar']:
        qml += self.indent(1, self.getInfobar(entry))
      else:
        qml += self.indent(1, self.getButton(entry))
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
    qmlRows = map(self.getRow, self.splitRows(maxRowLen))
    if self.center:
      anchorFct = "centerIn"
    else:
      anchorFct = "fill"
    qml = ""
    qml += "Rectangle{\n"
    qml += "  width: " + str(self.width) + "\n"
    qml += "  height: " + str(self.height) + "\n"
    qml += "  rotation: " + str(rotationDegrees) + "\n"
    qml += "  Column{\n"
    qml += "    spacing: 10\n"
    qml += "    anchors." + anchorFct + ": parent\n"
    qml +=      self.indent(2, "\n".join(qmlRows))
    qml += "  }\n"
    qml += "}\n"
    return qml

  def getRow(self, row):
    qml = ""
    qml += "Row{\n"
    qml += "  spacing: 10\n"
    for entry in row:
      qml += "  Loader { sourceComponent: " + entry['widgetId'] + " }\n"
    qml += "}"
    return qml


  def splitRows(self, maxRowLen):
    rows = []
    row = []
    for entry in self.entries:
      if entry['infobar']:
        if len(row) > 0:
          rows.append(row)
          row = []
        rows.append([entry])
      elif entry['rowbreak']:
        if len(row) > 0:
          rows.append(row)
          row = []
      else:
        if len(row) >= maxRowLen:
          rows.append(row)
          row = []
        row.append(entry)
    if len(row) > 0:
      rows.append(row)
      row = []
    return rows

  def getHeader(self):
    return """
      import QtQuick 2.3

      Rectangle {
    """
  def getFooter(self):
    return """
      }
    """

  def getInfobar(self, entry):
    return """
        Component{
          id: %(widgetId)s
          Text {
            property string infobarWidgetId: "%(widgetId)s"
            objectName: "infobar"
            font.pointSize: 32
            width: 100
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
          property variant buttonColorGradient: "white"
          property variant buttonColorClicked: Qt.lighter(buttonColorDefault)
          property variant buttonColorHover: Qt.darker(buttonColorDefault)

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
          width: 150
          height: 180
        }
      }
    """ % entry


class CommandRunner(QObject):
  def __init__(self, mainWindow, entries, infobarWidgets):
    QObject.__init__(self, mainWindow)
    self.mainWindow = mainWindow
    self.entries = entries
    self.infobarWidgets = infobarWidgets

    self.cmdsByWidgetId = {}
    for entry in entries:
      self.cmdsByWidgetId[entry["widgetId"]] = entry["command"]

    self.infobarsTimerIntervalMillis = 1000
    self.infobarsTimer = QTimer(self)
    self.infobarsTimer.timeout.connect(self.updateInfobars)
    self.setInfobarsTimerEnabled(True)
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
    if not self.mainWindow.isActive():
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
  def __init__(self, qmlFile, entries):
    super(MainWindow, self).__init__(None)
    self.setSource(QUrl(qmlFile))

    infobarWidgets = self.rootObject().findChildren(QObject, "infobar")
    self.commandRunner = CommandRunner(self, entries, infobarWidgets)
    self.commandRunner.updateInfobars()
    self.rootContext().setContextProperty("commandRunner", self.commandRunner)

class Config():
  def __init__(self, confFile):
    self.confFile = confFile
  def getEntry(self, number, name, icon, command, infobar=False, rowbreak=False):
    if rowbreak:
      widgetId = None
    elif infobar:
      widgetId = "infobar" + str(number)
    else:
      widgetId = "button" + str(number)
    return { "widgetId": widgetId
           , "name": name
           , "icon": self.getIconPath(icon)
           , "command": command
           , "infobar": infobar
           , "rowbreak": rowbreak
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
      csv = entry.split(',', 3)
      if len(csv) == 1 and csv[0].strip() == "rowbreak":
        cmds.append(self.getEntry(number, None, None, None, False, True))
      elif len(csv) == 2 and csv[0].strip() == "infobar":
        cmd = csv[1].strip()
        cmds.append(self.getEntry(number, None, None, cmd, True))
        number+=1
      elif len(csv) == 3:
        name = csv[0].strip()
        icon = csv[1].strip()
        cmd = csv[2].strip()
        cmds.append(self.getEntry(number, name, icon, cmd))
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
