# Local Wi-Fi Speed Tester

Local Wi-Fi Speed Tester measures how fast one device can communicate with another device on the same home network. It is different from internet speed tests because it checks your local Wi-Fi/router performance instead of your connection to an outside server.

## What it measures

- Ping/latency: how long a tiny message takes to travel to the server and back.
- Upload speed: how fast the client can send data to the server.
- Download speed: how fast the client can receive data from the server.
- Stability: whether per-second speeds stay consistent or have noticeable drops.
- Recommendations: short guidance based on latency, speed, and stability.

## Setup

Create and activate the virtual environment:

```bash
python3 -m venv lwst_venv
source lwst_venv/bin/activate
```

This project currently uses only the Python standard library at runtime, so there are no required packages to install for the tester itself.

## Run a Test

You can use either the desktop app or the command-line scripts.

### Desktop App

Start the app:

```bash
python app.py
```

For a real Wi-Fi test, use two computers:

1. On the first computer, open the `Server` tab and click `Start Server`.
2. Write down the IP address and port shown in the server log.
3. On the second computer, open the `Client` tab.
4. Enter the server IP, port, duration, and a location name.
5. Click `Run Test`.

The `History` tab reads `results.csv` so you can compare rooms, devices, Wi-Fi bands, or Ethernet later.

For a same-computer app check, start the server in the `Server` tab, then use this in the `Client` tab:

```text
Server IP: 127.0.0.1
Port: 5055
Location: Same Computer
```

That confirms the app works, but it does not measure real Wi-Fi speed.

### Command Line

Run the server on one device connected to your Wi-Fi or router:

```bash
python server.py
```

The server prints an address like:

```text
Server running on 192.168.1.25:5000
Waiting for client...
```

Run the client on the computer you want to test:

```bash
python client.py
```

When the client asks questions, enter values like:

```text
Enter server IP: 192.168.1.25
Enter test duration in seconds [10]: 10
Enter test location/name: Bedroom
```

Or provide everything with flags:

```bash
python client.py --server 192.168.1.25 --duration 10 --location Bedroom
```

## Same-Computer Test

You can run the server and client on the same computer to check that the program works:

```bash
python server.py --host 127.0.0.1 --port 5000
```

Then open another terminal and run:

```bash
python client.py --server 127.0.0.1 --port 5000 --duration 3 --location "Same Computer"
```

This is only an app/protocol test. It does not measure real Wi-Fi speed because the data stays inside the same computer instead of traveling through your router.

## Results

The client prints a report with average ping, upload Mbps, download Mbps, min/max per-second speed, stability, and a recommendation. By default it also appends each run to `results.csv`:

```csv
date,location,upload_mbps,download_mbps,ping_ms,stability
2026-05-06T14:30:00,Bedroom,280.00,350.00,9.00,Good
```

Use location names like `Bedroom`, `Near Router`, `Office`, `2.4 GHz`, `5 GHz`, or `Ethernet` so the CSV becomes useful for comparing tests later.

## Useful Options

```bash
python app.py
python server.py --host 0.0.0.0 --port 5000
python client.py --server 192.168.1.25 --port 5000 --duration 5 --location "Near Router"
python client.py --server 192.168.1.25 --no-save
```

## Windows App Notes

The desktop app uses Tkinter, which ships with normal Python installs on Windows. To run it from source:

```powershell
py -m venv lwst_venv
lwst_venv\Scripts\activate
py app.py
```

To package it later as a single Windows executable:

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed app.py
```

The executable will be created in `dist`. Windows may ask whether to allow network access when running the server; allow private network access for real local Wi-Fi tests.

On some Linux installs, Tkinter is a separate system package. If `python app.py` says `No module named 'tkinter'`, install the OS package for Tkinter, then run the app again.

## Notes

- Both devices must be on the same local network.
- Firewalls may ask for permission to allow Python to accept local network connections.
- For best comparisons, keep the test duration the same between locations.
- This measures local network throughput, not your internet provider speed.
