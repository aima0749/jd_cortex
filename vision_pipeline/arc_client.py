"""
ARC TCP Exec client.

Connects to ARC's TCP Shell Server (default port 6666) and sends text
commands, exactly as if typed into ARC's own script editor. This is the
same mechanism the original project brief planned to use for servo
commands later - we're using it first here just to trigger camera frame
saves, since ARC's camera-server/network-streaming UI wasn't available
in this ARC version.

Usage as a module (imported by the pipeline script):
    from arc_client import ArcClient
    arc = ArcClient(host="127.0.0.1", port=6666)
    arc.connect()
    arc.send_command('CameraSaveImage(0, "C:\\\\path\\\\to\\\\live_frame.jpg")')
    arc.close()

Run directly to test the connection on its own:
    python arc_client.py
"""

import socket
import time
import os


class ArcClient:
    def __init__(self, host="127.0.0.1", port=6666, timeout=5):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        print(f"Connected to ARC TCP server at {self.host}:{self.port}")

    def send_command(self, command: str, read_response=True, wait=0.3):
        if self.sock is None:
            raise RuntimeError("Not connected. Call connect() first.")
        message = command.strip() + "\n"
        self.sock.sendall(message.encode("utf-8"))
        if read_response:
            time.sleep(wait)
            try:
                self.sock.settimeout(1.0)
                response = self.sock.recv(4096).decode("utf-8", errors="replace")
                return response
            except socket.timeout:
                return "(no response received)"
        return None

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def cleanup_old_snapshots(snapshot_folder, keep_file=None):
    """Deletes all files in the snapshot folder except the one we just
    read (keep_file). Prevents 'My Robot Pictures' from filling up disk
    space over a long running session."""
    if not os.path.isdir(snapshot_folder):
        return
    for f in os.listdir(snapshot_folder):
        full_path = os.path.join(snapshot_folder, f)
        if full_path != keep_file:
            try:
                os.remove(full_path)
            except OSError:
                pass  # file might be mid-write by ARC, skip it this round


def poll_loop(host="127.0.0.1", port=6666, snapshot_folder=None, iterations=20):
    """Repeatedly triggers a snapshot and reads the newest file, timing
    each cycle. Deletes old snapshot files each round to avoid filling
    up disk space. Used to measure how fast this approach can realistically run."""
    if snapshot_folder is None:
        snapshot_folder = os.path.join(os.path.expanduser("~"), "Pictures", "My Robot Pictures")

    client = ArcClient(host=host, port=port)
    client.connect()

    times = []
    last_seen_file = None

    for i in range(iterations):
        start = time.time()
        client.send_command('controlCommand("Camera Snapshot", "CameraSnapshot")', read_response=False)

        # wait briefly for the file to actually appear/update
        newest = None
        for _ in range(20):  # up to ~1s of polling for the new file
            if os.path.isdir(snapshot_folder):
                files = [os.path.join(snapshot_folder, f) for f in os.listdir(snapshot_folder)]
                if files:
                    candidate = max(files, key=os.path.getmtime)
                    if candidate != last_seen_file:
                        newest = candidate
                        break
            time.sleep(0.05)

        elapsed = time.time() - start
        times.append(elapsed)

        # Clean up: delete every snapshot file except the one we just read,
        # so disk space never accumulates.
        cleanup_old_snapshots(snapshot_folder, keep_file=newest)

        last_seen_file = newest if newest else last_seen_file
        print(f"Frame {i+1}/{iterations}: {elapsed:.3f}s  file={os.path.basename(newest) if newest else 'NONE'}")

    client.close()

    # Final cleanup - remove the last leftover file too, folder ends empty
    cleanup_old_snapshots(snapshot_folder, keep_file=None)

    avg = sum(times) / len(times)
    print(f"\nAverage time per frame: {avg:.3f}s  (~{1/avg:.1f} FPS)")
    print("Snapshot folder cleaned up - no leftover files.")


if __name__ == "__main__":
    # Quick standalone test: connect, ask ARC to save a camera snapshot, disconnect.
    HOST = "127.0.0.1"
    PORT = 6666
    SNAPSHOT_FOLDER = os.path.join(os.path.expanduser("~"), "Pictures", "My Robot Pictures")

    print("Running a 20-frame polling speed test...")
    print("(This tells us the realistic FPS this snapshot-loop approach can hit)")
    poll_loop(host=HOST, port=PORT, snapshot_folder=SNAPSHOT_FOLDER, iterations=20)