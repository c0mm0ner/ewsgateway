#!/usr/bin/python2

# ewsgateway.py: A simple gateway to access the Embedded Web Server
# (EWS) on several models of HP printers via USB.
#
# Copyright (c) 2011 Jared Stafford (jspenguin@gmail.com)
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# 3. The name of the author may not be used to endorse or promote products
#   derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


# Copyright (C) 2015 c0mm0ner projekt@w3b0.de
# Small changes for running ewsgateway on Archlinux
#   - shebang changed to python2
#   - catching usb.USBError on dev.open()
#   - added plain sudo as an option for privilege escalation

import sys
import os
import usb
import random
import socket
import threading
import traceback
import webbrowser

from subprocess import call

from cStringIO import StringIO
from Tkinter import *
from os.path import *

import tkMessageBox

# HP
VENDORS = (0x03f0,)
def filter_dev(dev, dh, manuf, product, serial):
    return dev.idVendor in VENDORS

def filter_interface(dev, dh, intf, name):
    return intf.interfaceClass == 255 and 'EWS' in name

HOST = 'localhost'
DEFAULT_PORT = 9980

SUDO_PROGS = ('sudo', 'gksudo', 'kdesudo', 'gksu', 'kdesu')


def getstr(dh, i):
    if not i:
        return ''
    try:
        return dh.getString(i, 128)
    except usb.USBError:
        return None

def get_devices():
    fail = False
    devs = []
    for bus in usb.busses():
        for dev in bus.devices:
            try:
                dh = dev.open()
            except usb.USBError:
                fail = True
                continue
            
            if fail is not True:
                ven = getstr(dh, dev.iManufacturer)
                mdl = getstr(dh, dev.iProduct)
                ser = getstr(dh, dev.iSerialNumber)

            if ven is None or mdl is None or ser is None:
                fail = True
                continue

            txt = []
            if ven:
                txt.append(ven)
            txt.append(mdl or '<unknown>')
            if ser:
                txt.append('(S/N %s)' % ser)
            txt = ' '.join(txt)

            if not filter_dev(dev, dh, ven, mdl, ser):
                continue
            
            for config in dev.configurations:
                for intf in config.interfaces:
                    for alt in intf:
                        name = getstr(dh, alt.iInterface)
                        if not filter_interface(dev, dh, alt, name):
                            continue
                        devs.append((txt, (dev, alt)))
    return fail, devs

def find_ep(intf, out, type):
    for i, ep in enumerate(intf.endpoints):
        isout = ep.address & usb.ENDPOINT_DIR_MASK == usb.ENDPOINT_OUT
        if isout == out and ep.type == type:
            return ep.address
        

class USBIO(object):
    def __init__(self, dev, intf):
        dh = dev.open()
        dh.claimInterface(intf)
        
        epin = find_ep(intf, False, usb.ENDPOINT_TYPE_BULK)
        epout = find_ep(intf, True, usb.ENDPOINT_TYPE_BULK)
        
        self.dh = dh
        self.epout = epout
        self.epin = epin
        self.buf = ''
        self.outbuf = ''
        self.tmo = 200
        
    def close(self):
        try:
            self.dh.releaseInterface()
        except usb.USBError:
            pass
        self.dh = None
        self.buf = self.outbuf = ''
        
    def write(self, dat):
        self.outbuf += dat
        
    def flush(self):
        self.dh.bulkWrite(self.epout, self.outbuf, self.tmo)
        self.outbuf = ''
        
    def rawread(self, len):
        return ''.join(chr(s) for s in self.dh.bulkRead(self.epin, len, self.tmo))
    
    def read(self, rl):
        while len(self.buf) < rl:
            self.buf += self.rawread(8192)
        rdat = self.buf[:rl]
        self.buf = self.buf[rl:]
        return rdat
            
    def readline(self):
        while True:
            idx = self.buf.find('\n')
            if idx != -1:
                rdat = self.buf[:idx + 1]
                self.buf = self.buf[idx + 1:]
                return rdat
            self.buf += self.rawread(8192)

    def drain(self):
        self.buf = ''
        while True:
            try:
                data = self.dh.bulkRead(self.epin, 8192, 50)
            except usb.USBError:
                break

try:
    strpart = str.partition
except:
    def strpart(s, k):
        l = s.split(k, 1)
        if len(l) == 1:
            return s, '', ''
        return l[0], k, l[1]

    
def gethdr(hdrs, key, default=None):
    key = key.lower()
    for k, v in hdrs:
        if k.lower() == key:
            return v
    return default

def sethdr(hdrs, key, newval):
    lkey = key.lower()
    for i, (k, v) in enumerate(hdrs):
        if k.lower() == lkey:
            hdrs[i] = k, newval
            return
    hdrs.append((key, newval))

def read_headers(io):
    hdrs = []
    while True:
        lin = io.readline().rstrip('\r\n')
        if not lin:
            break
        k, s, v = strpart(lin, ':')
        if not s: # wtf?
            continue
        hdrs.append((k, v.lstrip(' ')))
    return hdrs

def write_headers(io, rhdrs):
    for k, v in rhdrs:
        #dbg('  send hdr: %s: %s' % (k, v))
        io.write('%s: %s\r\n' % (k, v))
    io.write('\r\n')
    io.flush()
    
def proxy_chunked(inp, outp):
    while True:
        clenhex = inp.readline()
        outp.write(clenhex)
        clen = int(clenhex.rstrip('\r\n'), 16)
        #dbg('  proxy_chunked: clen=%d' % clen)
        if clen != 0:
            outp.write(inp.read(clen))
        outp.write(inp.readline())
        outp.flush()
        if clen == 0:
            break

def proxy_body(inp, outp, hdrs):
    encoding = gethdr(hdrs, 'transfer-encoding', '').lower()
    if encoding == 'chunked':
        proxy_chunked(inp, outp)
    else:
        clen = gethdr(hdrs, 'content-length', None)
        try:
            clen = int(clen)
            if clen > 0:
                outp.write(inp.read(clen))
            outp.flush()
        except (ValueError, TypeError):
            pass

def proxy_request(io, sock):
    rqline = sock.readline().rstrip('\r\n')
    #dbg('request line: %s' % rqline)

    l = rqline.split(' ', 2)
    if len(l) != 3:
        sock.write('HTTP/1.1 400 Bad request\r\n\r\nBad request\r\n')
        return
    method = l[0]
    
    rqhdrs = read_headers(sock)

    sethdr(rqhdrs, 'Connection', 'Close')
    sethdr(rqhdrs, 'Host', 'localhost')

    io.write(rqline + '\r\n')
    write_headers(io, rqhdrs)
    if method == 'POST':
        proxy_body(sock, io, rqhdrs)

    rspline = io.readline().rstrip('\r\n')
    #dbg('response: %s' % rspline)
    sock.write(rspline + '\r\n')
    rsphdrs = read_headers(io)
    sethdr(rsphdrs, 'Connection', 'Close')
    write_headers(sock, rsphdrs)
    if method != 'HEAD':
        proxy_body(io, sock, rsphdrs)
    
    

    
class ServerThread(threading.Thread):
    def __init__(self, dev, port):
        threading.Thread.__init__(self)
        self.port = port
        self.dev = dev

        self.svr = svr = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        svr.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        svr.bind((HOST, port))
        svr.listen(1)

        self.csock = None
        self.csfile = None

        self.wantstop = False

        dev, intf = dev

        self.uio = uio = USBIO(dev, intf)

    def killsvr(self):
        self.wantstop = True
        try:
            self.svr.shutdown(socket.SHUT_RDWR)
            self.svr.close()
        except Exception:
            pass
        
        self.svr = None
        self.killclient()
        
    def killclient(self):
        try:
            self.csock.shutdown(socket.SHUT_RDWR)
            self.csock.close()
        except Exception:
            pass

        try:
            self.csfile.close()
        except Exception:
            pass
        self.csock = None
        self.csfile = None

    def run(self):
        self.uio.drain()
        try:
            while not self.wantstop:
                try:
                    csock, addr = self.svr.accept()
                    self.csock = csock
                    self.csfile = sockf = csock.makefile('r+b')
                    proxy_request(self.uio, sockf)
                except Exception:
                    self.uio.drain()
                    if not self.wantstop:
                        traceback.print_exc()
                finally:
                    self.killclient()
        finally:
            self.uio.close()
            self.uio = None
        
class DeviceSelectDialog(object):

    def __init__(self, master):
        master.title("HP EWS Gateway")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.frame = frame = Frame(master)
        frame.grid(padx=5, pady=5, sticky=W+E+N+S)
        Label(frame, text="Available devices:").grid(sticky=W, columnspan=2)

        lbframe = Frame(frame)
        lbframe.grid(row=1, sticky=W+E+N+S, columnspan=2)
        self.list = Listbox(lbframe, selectmode=SINGLE, exportselection=0)
        self.list.grid(sticky=N+E+W+S)
        lscroll = Scrollbar(lbframe, orient=VERTICAL, takefocus=0)
        lscroll.grid(row=0, column=1, sticky=N+S)
        self.list['yscrollcommand'] = lscroll.set
        lscroll['command'] = self.list.yview
        
        lbframe.columnconfigure(0, weight=1)
        lbframe.rowconfigure(0, weight=1)

        self.selected_device = None
        
        Label(frame, text="Server port: ").grid(row=2, sticky=E)
        self.port_entry = Spinbox(frame, from_=1, to=65535, width=6, increment=1)
        self.port_entry.delete(0, END)
        self.port_entry.insert(END, str(DEFAULT_PORT))
        self.port_entry.grid(row=2, column=1, sticky=W+E)

        self.rfbutton = rfbutton = Button(frame, text="Refresh", command=self.refresh)
        rfbutton.grid(row=3, sticky=W+E)

        self.lbutton = lbutton = Button(frame, text="Launch browser", command=self.launch, state=DISABLED)
        lbutton.grid(row=3, column=1, sticky=W+E)
        
        self.stbutton = stbutton = Button(frame, text="Start", command=self.startstop)
        stbutton.grid(row=4, sticky=W+E)
        qbutton = Button(frame, text="Quit", command=self.quit)
        qbutton.grid(row=4, column=1, sticky=W+E)

        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1, minsize=300)
        frame.columnconfigure(1, weight=1, minsize=300)

        self.svthread = None
        self.refresh()


    def setbuttons(self):
        if self.svthread is not None:
            rstate = NORMAL
            sstate = DISABLED
            self.stbutton['text'] = "Stop"
        else:
            self.stbutton['text'] = "Start"
            rstate = DISABLED
            sstate = NORMAL
            
        for b in (self.list, self.rfbutton, self.port_entry):
            b['state'] = sstate
        self.lbutton['state'] = rstate
        if self.devices:
            self.stbutton['state'] = NORMAL
        else:
            self.stbutton['state'] = DISABLED
            
    def launch(self):
        if os.geteuid() == 0:
            runbrowser = tkMessageBox.askyesno("Warning", "Running a browser as root can be a security risk. "
                                               "You may access the EWS by visiting http://%s:%d/ in your normal browser.\n\n"
                                               "Open browser as root?" % (HOST, self.server_port), default="no")
            if not runbrowser:
                return
            
        webbrowser.open('http://%s:%d/' % (HOST, self.server_port))

    def startstop(self):
        if self.svthread:
            self.stop()
        else:
            self.start()
            
    def start(self):
        ptxt = self.port_entry.get()
        try:
            sport = int(ptxt)
        except ValueError:
            tkMessageBox.showerror("Invalid value", "Invalid port value: %s" % ptxt)
            return
        
        self.server_port = sport

        cdev = self.list.curselection()
        if len(cdev) != 1:
            tkMessageBox.showerror("Error", "No device selected")
            return

        dev = self.devices[int(cdev[0])][1]
        try:
            thr = ServerThread(dev, sport)
            thr.start()
        except Exception, exc:
            traceback.print_exc()
            tkMessageBox.showerror("Error", "Could not start server: %s" % exc)
            return
        self.svthread = thr
        self.setbuttons()
            
    def stop(self):
        self.svthread.killsvr()
        self.svthread.join()
        self.svthread = None
        try:
            self.setbuttons()
        except Exception:
            # we may get an error while shutting down
            pass
        
    def quit(self):
        if self.svthread:
            self.stop()
        self.frame.winfo_toplevel().destroy()
        self.frame.quit()
        
        
    def refresh(self):
        defv = None
        cdev = self.list.curselection()
        if len(cdev) == 1:
            defv = int(cdev[0])
        fail, devs = get_devices()

        if fail:
            if os.geteuid() == 0:
                tkMessageBox.showwarning("Warning", "Could not access some devices.")
            else:
                runroot = tkMessageBox.askyesno("Warning", "Could not access some devices. "
                                                   "Would you like to try running as root?", default="no")
                if runroot:
                    self.quit()
                    for sp in SUDO_PROGS:
                        try:
                            os.execvp(sp, [sp, sys.executable, __file__])
                            sys.exit(0)
                        except OSError:
                            pass
                    
                    tkMessageBox.showerror("Error", "Could not run gksudo or kdesu.")
                    sys.exit(0)
                
        
        self.devices = devs
        self.list.delete(0, END)
        for name, val in devs:
            self.list.insert(END, name)

        if not devs:
            self.list.insert(END, '<no devices available>')

        if defv is not None and defv < len(devs):
            self.list.selection_set(defv)
        elif devs:
            self.list.selection_set(0)
        self.setbuttons()
        
def main():
    root = Tk()
    app = DeviceSelectDialog(root)
    try:
        root.mainloop()
    finally:
        if app.svthread:
            app.stop()

main()
