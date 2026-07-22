"""
Low-level TCP connection to ARC. Every other module in this project uses
this instead of opening its own socket, so there's exactly one connection
lifecycle to reason about, in one place.
"""
import socket
from config import ARC_HOST, ARC_PORT, CONNECT_TIMEOUT


class ARCConnection:
    def __init__(self):
        self.sock = None

    def connect(self):
        print(f"Connecting to ARC at {ARC_HOST}:{ARC_PORT}...")
        try:
            self.sock = socket.create_connection((ARC_HOST, ARC_PORT), timeout=CONNECT_TIMEOUT)
        except OSError as e:
            print(f"FAILED to connect: {e}")
            print("Check: is ARC open, project loaded, and the real robot connected?")
            return False
        print("Connected.\n")
        return True

    def disconnect(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            print("Disconnected.")

    def send(self, command_text):
        if not self.sock:
            raise RuntimeError("Not connected to ARC.")
        self.sock.sendall((command_text.strip() + "\n").encode("utf-8"))

    def receive(self, timeout=2.0):
        if not self.sock:
            raise RuntimeError("Not connected to ARC.")
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(4096).decode("utf-8", errors="ignore").strip()
        except socket.timeout:
            return ""
        finally:
            self.sock.settimeout(None)

    def send_and_receive(self, command_text, timeout=2.0):
        self.send(command_text)
        return self.receive(timeout)
