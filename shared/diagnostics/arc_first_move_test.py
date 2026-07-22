"""
ARC Integration - First Move Test
--------------------------------------
The smallest possible test: connect to ARC over TCP, send ONE servo
command, confirm it actually moves something in ARC (simulator or real
hardware). Nothing else - no move library, no Gemini, no vision. Just
proving the socket connection and command syntax actually work.

Before running this:
  1. Open your ARC project
  2. Add a servo control (a virtual servo port like V0 is fine for
     this first test - no physical hardware required)
  3. Confirm ARC is running and listening for connections

Run:
    python arc_first_move_test.py
"""

import socket
import time

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666

def send_command(sock, command_text):
    """Sends one EZ-Script command line to ARC. Commands must end in \n."""
    full_command = command_text.strip() + "\n"
    sock.sendall(full_command.encode("utf-8"))
    print(f"Sent: {command_text}")

def main():
    print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
    try:
        sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=5)
    except OSError as e:
        print(f"FAILED to connect: {e}")
        print("Check: is ARC open? Is the project loaded? Is the TCP/script")
        print("interface enabled and listening on this port?")
        return

    print("Connected. Sending test servo command...\n")

    # trigger the "Bow" Auto Position frame - already proven to work
    # when typed manually into ARC's console
    send_command(sock, 'ControlCommand("Auto Position", AutoPositionFrame, "Bow")')
    time.sleep(3)  # give the pose time to actually play out

    sock.close()
    print("\nDone. Check ARC - did the servo (or its on-screen indicator) move?")

if __name__ == "__main__":
    main()