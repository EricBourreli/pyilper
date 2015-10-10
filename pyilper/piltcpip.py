﻿#!/usr/bin/python3
# -*- coding: utf-8 -*-
# pyILPER 1.2.1 for Linux
#
# An emulator for virtual HP-IL devices for the PIL-Box
# derived from ILPER 1.4.5 for Windows
# Copyright (c) 2008-2013   Jean-Francois Garnier
# C++ version (c) 2013 Christoph Gießelink
# Python Version (c) 2015 Joachim Siebold
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# tcpip object class  ---------------------------------------------
#
# Initial version derived from ILPER 1.43
#
# Changelog
#
# 24.09.2015 cg
# - added real IPv4/IPv6 dual stack mode
# - reconnecting server and client work now
# - broken loop don't crash connection any more
# - removed some unused class variables
# 05.10.2015 jsi
# - class statement syntax update

import time
import select
import socket
import threading

class TcpIpError(Exception):
   def __init__(self,msg,add_msg=None):
      self.msg = msg
      self.add_msg = add_msg

class cls_piltcpip:

   def __init__(self,port,remotehost,remoteport):
      self.__port__=port       # port for input connection
      self.__remotehost__=remotehost     # host for output connection
      self.__remoteport__=remoteport     # port for output connection

      self.__running__ = False     # Connected to Network
      self.__srq__= False          # PIL-Box SRQ State
      self.__devices__ = []        # list of virtual devices
      self.srqflags = 0            # flag of devices to set srqflag
      self.__devicecounter__=0     # counter of added devices
      self.__timestamp__= time.time()   # time of last activity
      self.__timestamp_lock__= threading.Lock()

      self.__serverlist__ = []
      self.__clientlist__= []
      self.__outsocket__= None
      self.__outconnected__= False

   def isConnected(self):
      return self.__outconnected__

   def gettimestamp(self):
      self.__timestamp_lock__.acquire()
      t= self.__timestamp__
      self.__timestamp_lock__.release()
      return t

#
#  Connect to Network
#
   def open(self):
#
#     open network connections
#
      host= None
      self.__serverlist__.clear()
      self.__clientlist__.clear()
      for res in socket.getaddrinfo(host, self.__port__, socket.AF_UNSPEC,
                              socket.SOCK_STREAM, 0, socket.AI_PASSIVE):
         af, socktype, proto, canonname, sa = res
         try:
            s = socket.socket(af, socktype, proto)
         except OSError as msg:
            s = None
            continue
         try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(sa)
            s.listen(1)
            self.__serverlist__.append(s)
         except OSError as msg:
            s.close()
            continue
      if len(self.__serverlist__) is 0:
         raise TcpIpError("cannot bind to port")
      self.__running__ = True

   def openclient(self):
#
#     connect to remote host
#
      self.__outsocket__ = None
      self.__outconnected__= False
      for res in socket.getaddrinfo(self.__remotehost__, self.__remoteport__, socket.AF_UNSPEC, socket.SOCK_STREAM):
         af, socktype, proto, canonname, sa = res
         try:
            self.__outsocket__ = socket.socket(af, socktype, proto)
         except OSError as msg:
            self.__outsocket__ = None
            continue
         try:
            self.__outsocket__.connect(sa)
            self.__outconnected__= True
         except OSError as msg:
            self.__outsocket__.close()
            self.__outsocket__ = None
            continue
         break

#
#  Disconnect from Network
#
   def close(self):
      for s in self.__clientlist__:
         s.close()
      for s in self.__serverlist__:
         s.close()
      if self.__outconnected__:
         self.__outsocket__.shutdown(socket.SHUT_WR)
         self.__outsocket__.close()
         self.__outsocket__= None
      self.__running__ = False

#
#  Read HP-IL frame from PIL-Box (2 byte), handle connect to server socket
#
   def read(self):
      readable,writable,errored=select.select(self.__serverlist__ + self.__clientlist__,[],[],0.1)
      for s in readable:
         if self.__serverlist__.count(s) > 0:
            cs,addr = s.accept()
            self.__clientlist__.append(cs)
         else:
            bytrx = s.recv(2)
            if bytrx:
               return (socket.ntohs((bytrx[1] << 8) | bytrx[0]))
            else:
               self.__clientlist__.remove(s)
               s.close()
      return None

#
#  Enable SRQ Mode
#
   def setServiceRequest(self):
      self.__srq__= True

#
#  Disable PIL-Box SRQ Mode
#
   def clearServiceRequest(self):
      self.__srq__= False

#
#     send a IL frame to the PIL-Box
#
   def sendFrame(self,frame):
      bRetry = False
      b=bytearray(2)
      f=socket.htons(frame)
      b[0]= f & 0xFF
      b[1]= f >> 8
      while True:
         if self.isConnected():
            try:
               self.__outsocket__.send(b)
               break
            except BrokenPipeError:
               raise TcpIpError ("remote program not available","")
            except ConnectionResetError:
               if bRetry:
                  raise TcpIpError ("reconnecting remote program failed","")
               else:
                  self.__outsocket__.shutdown(socket.SHUT_WR)
                  self.__outsocket__.close()
                  self.__outsocket__= None
                  self.__outconnected__ = False
                  bRetry = True
         else:
            self.openclient()

#
#  process frame
#
   def process(self,frame):

      self.__timestamp_lock__.acquire()
      self.__timestamp__= time.time()   # time of last activity
      self.__timestamp_lock__.release()
#
#     process virtual HP-IL devices
#
      for i in self.__devices__:
         frame=i.process(frame)
#     self.request_service()
#
#     If received a cmd frame from the PIL-Box send RFC frame to virtual
#     HPIL-Devices
#
#     if (frame & 0x700) == 0x400:
#        for i in self.__devices__:
#           frame=i.process(0x500)
#        self.request_service()
#
#     send frame
#
      self.sendFrame(frame)

#
#  toogle service request mode of PIL-Box
#
   def request_service(self):
      if self.srqflags and not self.__srq__:
         self.setServiceRequest()
      if not self.srqflags and self.__srq__:
         self.clearServiceRequest()

   def request_service2(self):
      switched=False
      if self.srqflags and not self.__srq__:
         switched=True
         self.__srq__= True
      return switched

#
#     virtual HP-IL device
#
   def register(self, obj):
      if self.__devicecounter__ > 16:
         raise TcpIpError("Too many virtual HP-IL devices (max 16)","")
      obj.setsrqbit(self.__devicecounter__)
      obj.setpilbox(self)
      self.__devices__.append(obj)
      self.__devicecounter__+=1
#
#     unregister virtual HP-IL device
#
   def unregister(self,n):
      del self.__devices__[n]
#
#     get-/set-
#
   def isRunning(self):
      return self.__running__
