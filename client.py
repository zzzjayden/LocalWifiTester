"""Client for the Local Wi-Fi Speed Tester.

Run this file on the computer whose local Wi-Fi speed you want to measure.
It connects to the server, measures ping/upload/download, prints a report,
and appends the result to results.csv.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import socket
import statistics
import time
from pathlib import Path


DEFAULT_PORT = 5000
DEFAULT_DURATION = 10.0
CHUNK_SIZE = 64 * 1024
PING_COUNT = 10
RESULTS_FILE = Path("results.csv")


def bytes_to_mbps(byte_count: int, seconds: float) -> float:
    """Convert bytes transferred over a duration into megabits per second."""
    return (byte_count * 8) / max(seconds, 0.000001) / 1_000_000


def read_line(sock: socket.socket) -> str:
    """Read a newline-terminated server response."""
    data = bytearray()
    while not data.endswith(b"\n"):
        part = sock.recv(1)
        if not part:
            break
        data.extend(part)
    return data.decode("utf-8", errors="replace").strip()


def connect(server_ip: str, port: int) -> socket.socket:
    """Open one TCP connection for one test command."""
    return socket.create_connection((server_ip, port), timeout=10)


def ping_test(server_ip: str, port: int, count: int = PING_COUNT) -> float:
    """Measure average round-trip time for tiny PING/PONG messages."""
    ping_times: list[float] = []

    for _ in range(count):
        with connect(server_ip, port) as sock:
            start = time.perf_counter()
            sock.sendall(b"PING\n")
            response = read_line(sock)
            elapsed_ms = (time.perf_counter() - start) * 1000

        if response != "PONG":
            raise RuntimeError(f"Unexpected ping response: {response!r}")
        ping_times.append(elapsed_ms)
        time.sleep(0.05)

    return statistics.mean(ping_times)


def record_second(samples: list[float], byte_count: int, seconds: float) -> None:
    """Save one per-second speed sample when enough time has passed."""
    if seconds > 0:
        samples.append(bytes_to_mbps(byte_count, seconds))


def upload_test(server_ip: str, port: int, duration: float) -> tuple[float, list[float]]:
    """Send data to the server for a fixed duration and return Mbps samples."""
    payload = b"\1" * CHUNK_SIZE
    total_bytes = 0
    second_bytes = 0
    per_second: list[float] = []

    with connect(server_ip, port) as sock:
        sock.settimeout(10)
        sock.sendall(b"UPLOAD_TEST\n")

        start = time.perf_counter()
        next_sample = start + 1

        while time.perf_counter() - start < duration:
            sent = sock.send(payload)
            total_bytes += sent
            second_bytes += sent

            now = time.perf_counter()
            if now >= next_sample:
                record_second(per_second, second_bytes, now - (next_sample - 1))
                second_bytes = 0
                next_sample = now + 1

        elapsed = time.perf_counter() - start
        remaining_seconds = elapsed - int(elapsed)
        if second_bytes:
            record_second(per_second, second_bytes, remaining_seconds or 1)

        # Half-close so the server sees EOF while this client can still read the
        # server's final "RECEIVED ..." response.
        sock.shutdown(socket.SHUT_WR)
        response = read_line(sock)

    if not response.startswith("RECEIVED "):
        raise RuntimeError(f"Unexpected upload response: {response!r}")

    return bytes_to_mbps(total_bytes, elapsed), per_second


def download_test(server_ip: str, port: int, duration: float) -> tuple[float, list[float]]:
    """Receive data from the server for a fixed duration and return Mbps samples."""
    total_bytes = 0
    second_bytes = 0
    per_second: list[float] = []

    with connect(server_ip, port) as sock:
        sock.settimeout(max(duration + 5, 10))
        sock.sendall(f"DOWNLOAD_TEST {duration}\n".encode("utf-8"))

        start = time.perf_counter()
        next_sample = start + 1

        while True:
            chunk = sock.recv(CHUNK_SIZE)
            if not chunk:
                break

            total_bytes += len(chunk)
            second_bytes += len(chunk)

            now = time.perf_counter()
            if now >= next_sample:
                record_second(per_second, second_bytes, now - (next_sample - 1))
                second_bytes = 0
                next_sample = now + 1

    elapsed = time.perf_counter() - start
    remaining_seconds = elapsed - int(elapsed)
    if second_bytes:
        record_second(per_second, second_bytes, remaining_seconds or 1)

    return bytes_to_mbps(total_bytes, elapsed), per_second


def stability_check(speed_list: list[float]) -> tuple[str, int]:
    """Rate stability by counting seconds below 60 percent of average speed."""
    if not speed_list:
        return "Not enough data", 0

    average_speed = statistics.mean(speed_list)
    drops = sum(1 for speed in speed_list if speed < average_speed * 0.60)

    if drops == 0:
        return "Excellent", drops
    if drops <= 2:
        return "Good, but had a few drops", drops
    return "Unstable", drops


def recommendation(ping_ms: float, download_mbps: float, stability: str) -> str:
    """Generate a short recommendation using the rules from the project brief."""
    if ping_ms > 50:
        return "Latency is high. Move closer to the router or check interference."
    if download_mbps < 100:
        return "Wi-Fi speed is low. Try 5 GHz, 6 GHz, or Ethernet."
    if stability == "Unstable":
        return "Connection has drops. Router distance or interference may be an issue."
    return "Your Wi-Fi is working well, but Ethernet would likely be faster and more stable."


def summarize_speeds(samples: list[float]) -> tuple[float, float]:
    """Return min/max values for a set of speed samples."""
    if not samples:
        return 0.0, 0.0
    return min(samples), max(samples)


def save_result(
    location: str,
    upload_mbps: float,
    download_mbps: float,
    ping_ms: float,
    stability: str,
    path: Path = RESULTS_FILE,
) -> None:
    """Append this test to CSV history for later comparison."""
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["date", "location", "upload_mbps", "download_mbps", "ping_ms", "stability"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "date": dt.datetime.now().isoformat(timespec="seconds"),
                "location": location,
                "upload_mbps": f"{upload_mbps:.2f}",
                "download_mbps": f"{download_mbps:.2f}",
                "ping_ms": f"{ping_ms:.2f}",
                "stability": stability,
            }
        )


def print_report(
    server_ip: str,
    duration: float,
    ping_ms: float,
    upload_mbps: float,
    upload_samples: list[float],
    download_mbps: float,
    download_samples: list[float],
    stability: str,
    drops: int,
) -> None:
    """Print a readable final report like the example in the PDF."""
    upload_min, upload_max = summarize_speeds(upload_samples)
    download_min, download_max = summarize_speeds(download_samples)

    print("\nLocal Wi-Fi Speed Test Results")
    print("------------------------------")
    print(f"Server IP: {server_ip}")
    print(f"Test duration: {duration:g} seconds")
    print("Ping:")
    print(f"Average ping: {ping_ms:.2f} ms")
    print("Upload:")
    print(f"Average speed: {upload_mbps:.2f} Mbps")
    print(f"Max speed: {upload_max:.2f} Mbps")
    print(f"Min speed: {upload_min:.2f} Mbps")
    print("Download:")
    print(f"Average speed: {download_mbps:.2f} Mbps")
    print(f"Max speed: {download_max:.2f} Mbps")
    print(f"Min speed: {download_min:.2f} Mbps")
    print("Stability:")
    print(f"{stability} ({drops} noticeable drop{'s' if drops != 1 else ''})")
    print("Recommendation:")
    print(recommendation(ping_ms, download_mbps, stability))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Wi-Fi speed test against a server.")
    parser.add_argument("--server", help="Server IP address, such as 192.168.1.25.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server TCP port.")
    parser.add_argument("--duration", type=float, help="Upload/download test duration in seconds.")
    parser.add_argument("--location", help="Label for this test, such as Bedroom or Near Router.")
    parser.add_argument("--no-save", action="store_true", help="Print results without appending results.csv.")
    return parser.parse_args()


def prompt_missing_args(args: argparse.Namespace) -> argparse.Namespace:
    """Ask for the main values when the user did not pass command-line flags."""
    if not args.server:
        print("Server IP example: 192.168.1.25")
        print("Same-computer app test example: 127.0.0.1")
        args.server = input("Enter server IP: ").strip()
    if args.duration is None:
        print("Duration example: 10 for a normal test, or 3 for a quick test.")
        raw_duration = input(f"Enter test duration in seconds [{DEFAULT_DURATION:g}]: ").strip()
        args.duration = float(raw_duration) if raw_duration else DEFAULT_DURATION
    if not args.location:
        print("Location example: Bedroom, Near Router, Office, 5 GHz, or Ethernet.")
        args.location = input("Enter test location/name: ").strip() or "Unknown"
    return args


def main() -> None:
    args = prompt_missing_args(parse_args())

    print("Running ping test...")
    ping_ms = ping_test(args.server, args.port)

    print("Running upload test...")
    upload_mbps, upload_samples = upload_test(args.server, args.port, args.duration)

    print("Running download test...")
    download_mbps, download_samples = download_test(args.server, args.port, args.duration)

    combined_samples = upload_samples + download_samples
    stability, drops = stability_check(combined_samples)

    print_report(
        args.server,
        args.duration,
        ping_ms,
        upload_mbps,
        upload_samples,
        download_mbps,
        download_samples,
        stability,
        drops,
    )

    if not args.no_save:
        save_result(args.location, upload_mbps, download_mbps, ping_ms, stability)
        print(f"\nSaved result to {RESULTS_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest cancelled.")
