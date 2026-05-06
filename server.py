"""Server for the Local Wi-Fi Speed Tester.

Run this file on the device that the test computer should connect to. The
server responds to ping requests, receives upload-test bytes, and sends
download-test bytes over your local network.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from collections.abc import Callable


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
CHUNK_SIZE = 64 * 1024
LogCallback = Callable[[str], None]


def get_lan_ip() -> str:
    """Return the best local IP address to show the user."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect does not send data here; it only lets the OS choose the
        # network interface that would reach the router/internet.
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def read_command(conn: socket.socket) -> str:
    """Read one newline-terminated command before any bulk test data starts."""
    data = bytearray()
    while not data.endswith(b"\n"):
        part = conn.recv(1)
        if not part:
            break
        data.extend(part)
    return data.decode("utf-8", errors="replace").strip()


def handle_client(conn: socket.socket, address: tuple[str, int], log: LogCallback = print) -> None:
    """Handle exactly one test command from a connected client."""
    with conn:
        command_line = read_command(conn)
        if not command_line:
            return

        parts = command_line.split()
        command = parts[0].upper()

        if command == "PING":
            conn.sendall(b"PONG\n")
            return

        if command == "UPLOAD_TEST":
            total_bytes = 0
            start = time.perf_counter()

            # The client half-closes its sending side when the timed upload is
            # done. EOF tells the server to stop counting and send the total.
            while True:
                chunk = conn.recv(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)

            elapsed = max(time.perf_counter() - start, 0.000001)
            conn.sendall(f"RECEIVED {total_bytes} {elapsed:.6f}\n".encode("utf-8"))
            log(f"Upload test from {address[0]}: received {total_bytes:,} bytes")
            return

        if command == "DOWNLOAD_TEST":
            try:
                duration = float(parts[1])
            except (IndexError, ValueError):
                conn.sendall(b"ERROR Missing or invalid duration\n")
                return

            block = b"\0" * CHUNK_SIZE
            deadline = time.perf_counter() + max(duration, 0.1)
            total_bytes = 0

            # Keep the socket busy until the deadline; the client measures how
            # many bytes arrive each second and computes the download speed.
            while time.perf_counter() < deadline:
                try:
                    conn.sendall(block)
                except (BrokenPipeError, ConnectionResetError):
                    break
                total_bytes += len(block)

            log(f"Download test to {address[0]}: sent {total_bytes:,} bytes")
            return

        if command == "QUIT":
            conn.sendall(b"BYE\n")
            return

        conn.sendall(f"ERROR Unknown command: {command}\n".encode("utf-8"))


class SpeedTestServer:
    """Small stoppable TCP server used by both the CLI and desktop app."""

    def __init__(self, host: str, port: int, log: LogCallback = print) -> None:
        self.host = host
        self.port = port
        self.log = log
        self._server: socket.socket | None = None
        self._stop_event = threading.Event()

    def serve_forever(self) -> None:
        """Start the TCP server and spawn a thread per connected client."""
        self._stop_event.clear()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self._server = server
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen()
            server.settimeout(0.5)

            self.log(f"Server running on {get_lan_ip()}:{self.port}")
            self.log("Waiting for client...")

            while not self._stop_event.is_set():
                try:
                    conn, address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                self.log(f"Client connected from {address[0]}:{address[1]}")
                thread = threading.Thread(target=handle_client, args=(conn, address, self.log), daemon=True)
                thread.start()

        self._server = None
        self.log("Server stopped.")

    def stop(self) -> None:
        """Ask the server loop to stop and close the listening socket."""
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass


def run_server(host: str, port: int) -> None:
    """Start the CLI server and keep it running until interrupted."""
    SpeedTestServer(host, port).serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Local Wi-Fi Speed Tester server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="IP/interface to bind to.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port to listen on.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run_server(args.host, args.port)
    except KeyboardInterrupt:
        print("\nServer stopped.")
