"""
Single Port Tester - test ONE port at a time, no rush
------------------------------------------------------------
Run this, type a port name, watch the robot, note what moved.
Type another port, repeat. No timer, no rushing - test each one
for as long as you need.

Run:
    python arc_single_port_test.py
"""

import socket

ARC_HOST = "127.0.0.1"
ARC_PORT = 6666


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

    print("Type a port name (like D0, D1, D2...) and press Enter.")
    print("Watch the robot. Type 'quit' to stop.\n")

    while True:
        port = input("Port to test (or 'quit'): ").strip()
        if port.lower() == "quit":
            break
        if not port:
            continue

        print(f"Moving {port} to 45...")
        send_command(sock, f"Servo({port}, 45)")
        input("Watch the robot now. Press Enter when you've seen enough...")

        print(f"Moving {port} back to 90...")
        send_command(sock, f"Servo({port}, 90)")
        print()

    sock.close()
    print("Done.")


if __name__ == "__main__":
    main()