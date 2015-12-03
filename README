======================================================================
                           USB EWS Gateway

             http://www.jspenguin.org/software/ewsgateway/     
======================================================================

A simple gateway to access the Embedded Web Server (EWS) on several
models of HP printers via USB.

HP printers have good driver support on Linux, but some models, like
the LaserJet Pro P1102w, have no way to set up wireless access without
connecting via USB to a Windows or Mac system. HPLIP has a tool called
hp-wificonfig, but it does not work on the P1102w.

Requirements:
  * Python (>= 2.5)
  * Tkinter (>= 2.5)
  * pyusb (or python-usb) (>= 0.4)

Usage:
  Run ewsgateway.py, select the device you want to access, then click
  "Start", then click "Launch browser". You may also open your browser
  manually and browse to http://localhost:9980/.

  If you don't have access to the device, you will be prompted to run
  as root, in which case you will need to enter your password.

  Once you have opened the browser, you can configure wireless by
  clicking on the "Networking" tab, then clicking "Wireless".

Troubleshooting:
  If your printer is not detected, try the following:

  * Make sure the printer is detected by the OS. Make sure you can set
    up the printer over USB and print a test page.

  * Check to see if the printer supports EWS. Open a terminal, run
    sudo lsusb -v, and look for "HP EWS".

If all else fails, you can contact me at jspenguin@gmail.com. Please
include the following information:

  * Your Linux distribution and version
  * Python version (python --version)
  * Output of LSUSB (sudo lsusb -v > lsusb.txt)
