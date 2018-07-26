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
DEFAULT_ICON_THEME_DIR = "hicolor"
DEFAULT_ICON_MAX_WIDTH = 256

signal.signal(signal.SIGINT, signal.SIG_DFL)

DBUS_SERVICE_PREFIX = "org.teleshoes.qtbtn"

usage = """Usage:
  %(exec)s CONFIG_FILE

  OPTIONS:
    --landscape
      align top of UI with longest screen dimenstion
        if screen width < screen height:
          rotate UI 90 degrees clockwise
        else
          do not rotate UI
    --portrait
      align top of UI with shortest screen dimenstion
        if screen width > screen height:
          rotate UI 90 degrees clockwise
        else
          do not rotate UI
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
  useDbus=False
  dbusServiceSuffix=None
  while len(args) > 0 and args[0].startswith("-"):
    arg = args.pop(0)
    dbusMatch = re.match("--dbus=([a-z]+)", arg)
    if arg == "--landscape":
      orientation = "landscape"
    elif arg == "--portrait":
      orientation = "portrait"
    elif dbusMatch:
      dbusServiceSuffix = dbusMatch.group(1)
      useDbus = True
    else:
      print >> sys.stderr, usage
      sys.exit(2)

  if len(args) != 1:
    print >> sys.stderr, usage
    sys.exit(2)

  configFile = args[0]

  app = QApplication([])

  geometry = app.desktop().availableGeometry()
  (screenWidth, screenHeight) = (geometry.width(), geometry.height())

  qml = QmlGenerator(screenWidth, screenHeight, orientation, configFile).getQml()
  fd, qmlFile = tempfile.mkstemp(prefix="qtbtn_", suffix=".qml")
  fh = open(qmlFile, 'w')
  fh.write(qml)
  fh.close()

  widget = MainWindow(qmlFile)

  if useDbus:
    app.setQuitOnLastWindowClosed(False)
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    service = DBUS_SERVICE_PREFIX + "." + dbusServiceSuffix
    qtBtnDbus = qtBtnDbusFactory(service)
    qtBtnDbus.signals.show.connect(widget.showFullScreen)
    qtBtnDbus.signals.hide.connect(widget.hide)
    qtBtnDbus.signals.quit.connect(QCoreApplication.instance().quit)
  else:
    widget.showFullScreen()

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
      print "show: " + dbusService
      self.signals.show.emit()

    @dbus.service.method(dbusService)
    def hide(self):
      print "hide: " + dbusService
      self.signals.hide.emit()

    @dbus.service.method(dbusService)
    def quit(self):
      print "quit: " + dbusService
      self.signals.quit.emit()

  return QtBtnDbus()

class QmlGenerator():
  def __init__(self, screenWidth, screenHeight, orientation, configFile):
    self.entries = Config(configFile).readConfFile()
    self.screenWidth = screenWidth
    self.screenHeight = screenHeight
    self.orientation = orientation
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
    minspaces = sys.maxint
    for line in lines:
      if len(line.strip(' ')) == 0:
        continue
      spaces = len(line) - len(line.lstrip(' '))
      minspaces = min(spaces, minspaces)
    newlines = []
    for line in lines:
      newlines.append('  ' * level + line[minspaces:] + "\n")
    return ''.join(newlines)

  def getMain(self):
    if self.orientation == "landscape" and self.screenWidth < self.screenHeight:
      rotationDegrees = 90
    elif self.orientation == "portrait" and self.screenWidth > self.screenHeight:
      rotationDegrees = 90
    else:
      rotationDegrees = 0

    return self.getLayout(self.landscapeMaxRowLen, rotationDegrees)

  def getLayout(self, maxRowLen, rotationDegrees):
    qmlRows = map(self.getRow, self.splitRows(maxRowLen))
    qml = ""
    qml += "Rectangle{\n"
    qml += "  width: " + str(self.screenWidth) + "\n"
    qml += "  height: " + str(self.screenHeight) + "\n"
    qml += "  rotation: " + str(rotationDegrees) + "\n"
    qml += "  Column{\n"
    qml += "    spacing: 10\n"
    qml += "    anchors.centerIn: parent\n"
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
            property string command: "%(command)s"
            objectName: "infobar"
            font.pointSize: 16
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
          property variant buttonColor: buttonColorDefault
          MouseArea {
            hoverEnabled: true
            anchors.fill: parent
            onClicked: commandRunner.runCommand("%(command)s")
            function setColor(){
              if(this.pressed){
                parent.buttonColor = Qt.lighter(parent.buttonColorDefault)
              }else if(this.containsMouse){
                parent.buttonColor = Qt.darker(parent.buttonColorDefault)
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
            font.pointSize: 16
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
          width: 100
          height: 120
        }
      }
    """ % entry


class CommandRunner(QObject):
  def __init__(self, infobars):
    QObject.__init__(self)
    self.infobars = infobars
  @pyqtSlot(str)
  def runCommand(self, command):
    os.system(command)
    time.sleep(0.5)
    self.updateInfobars()
  def updateInfobars(self):
    cmdCache = {}
    for infobar in self.infobars:
      cmd = infobar.property("command")
      if cmd in cmdCache:
        msg = cmdCache[cmd]
      else:
        print "  running infobar command: " + cmd

        try:
          proc = subprocess.Popen(['sh', '-c', cmd],
            stdout=subprocess.PIPE)
          msg = proc.stdout.readline()
          proc.terminate()
          cmdCache[cmd] = msg
        except:
          msg = "ERROR"
      infobar.setProperty("text", msg)

class MainWindow(QQuickView):
  def __init__(self, qmlFile):
    super(MainWindow, self).__init__(None)
    self.setSource(QUrl(qmlFile))

    infobars = self.rootObject().findChildren(QObject, "infobar")
    self.commandRunner = CommandRunner(infobars)
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
    if icon != None and os.path.isfile(icon):
      return os.path.abspath(icon)
    else:
      return self.findIcon(icon,
        DEFAULT_ICON_DIR, DEFAULT_ICON_THEME_DIR, DEFAULT_ICON_MAX_WIDTH)
  def findIcon(self, iconName, iconBaseDir, themeName, maxWidth):
    if iconName == None:
      return ""

    iconName = re.sub('\.\w+$', '', iconName)
    iconName = iconName.lower()

    dirs = glob.glob(iconBaseDir + "/" + themeName + "/*x*/")
    for iconDir in dirs:
      m = re.match('/(\d+)x(\d)+/', iconDir)
      if m:
        dirWidth = int(m.group(1))
        dirHeight = int(m.group(2))
        if dirWidth > maxWidth:
          next

      for root, dirs, files in os.walk(iconDir):
        for f in files:
          if re.match('^' + iconName + '\.\w+$', f.lower()):
            return root + "/" + f

    return ""
  def readConfFile(self):
    if not os.path.exists(self.confFile):
      print >> sys.stderr, self.confFile + " is missing"
      sys.exit(1)
    cmds = []
    number = 0
    for line in file(self.confFile).readlines():
      line = line.partition('#')[0]
      line = line.strip()
      if len(line) > 0:
        csv = line.split(',', 3)
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

if __name__ == "__main__":
  sys.exit(main())
