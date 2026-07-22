"""
ARC Port Scanner - find which port actually moves something
-------------------------------------------------------------------
Runs entirely from Python/CMD - no typing into ARC's console needed.
Cycles through servo ports one at a time, moving each briefly, with a
pause so you can watch the real robot and see which port (if any)
actually causes movement.

Run:
    python arc_port_scanner.py

While it's running: WATCH THE REAL ROBOT. When you see something move,
note the port number printed just before it, then press Ctrl+C to stop.
"""

import socket
import time

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666

# how many ports to test - adjust if JD has more/fewer
PORTS_TO_TEST = [f"D{i}" for i in range(0, 16)]

PAUSE_BETWEEN_PORTS = 2.5  # seconds - gives you time to actually see it


def send_command(sock, command_text):
    full_command = command_text.strip() + "\n"
    sock.sendall(full_command.encode("utf-8"))


def main():
    print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
    try:
        sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=5)
    except OSError as e:
        print(f"FAILED to connect: {e}")
        return

    print("Connected.\n")
    print("Watch the REAL robot now. Testing each port for 2.5 seconds.")
    print("The moment you see something move, note the port shown, then")
    print("press Ctrl+C to stop.\n")
    time.sleep(2)

    try:
        for port in PORTS_TO_TEST:
            print(f"--- Testing {port}: moving to 45 ---")
            send_command(sock, f"Servo({port}, 45)")
            time.sleep(PAUSE_BETWEEN_PORTS)

            print(f"--- Testing {port}: moving back to 90 ---")
            send_command(sock, f"Servo({port}, 90)")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped by user.")

    sock.close()
    print("\nDone scanning. Whichever port you saw move - that's the real one.")


if __name__ == "__main__":
    main()