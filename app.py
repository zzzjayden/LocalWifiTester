"""Desktop app for Local Wi-Fi Speed Tester.

The app wraps the same server/client logic as the command-line scripts. One
computer can run the Server tab, and another computer can run the Client tab to
measure real local Wi-Fi speed.
"""

from __future__ import annotations

import csv
import os
import queue
import threading
from pathlib import Path

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Tkinter is not installed for this Python.\n"
        "On Ubuntu/WSL, install it with:\n"
        "  sudo apt update && sudo apt install python3-tk\n"
        "Then run:\n"
        "  source lwst_venv/bin/activate\n"
        "  python app.py"
    ) from exc

import client
from server import SpeedTestServer


APP_PORT = 5055
HISTORY_COLUMNS = ("date", "location", "upload_mbps", "download_mbps", "ping_ms", "stability")
SAGE_DARK = "#4f5743"
SAGE = "#6b7460"
CREAM = "#dcd1c3"
TAUPE = "#b29784"
INK = "#25291f"
PANEL = "#eee7dc"
WHITE = "#fbf8f2"
DARK_TEXT = "#f2eadf"


class LocalWifiTesterApp(tk.Tk):
    """Tkinter desktop app with server, client, and history views."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Local Wi-Fi Speed Tester")
        self.minsize(820, 560)

        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.server: SpeedTestServer | None = None
        self.server_thread: threading.Thread | None = None
        self.test_thread: threading.Thread | None = None

        self.server_host = tk.StringVar(value="0.0.0.0")
        self.server_port = tk.StringVar(value=str(APP_PORT))
        self.client_ip = tk.StringVar(value="127.0.0.1")
        self.client_port = tk.StringVar(value=str(APP_PORT))
        self.duration = tk.StringVar(value="10")
        self.location = tk.StringVar(value="Bedroom")
        self.status_text = tk.StringVar(value="Ready")
        self.tab_buttons: dict[str, tk.Button] = {}
        self.tab_frames: dict[str, tk.Frame] = {}

        self._build_ui()
        self._poll_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.configure(bg=CREAM)
        style.configure(".", background=CREAM, foreground=INK, font=("TkDefaultFont", 10))
        style.configure("TFrame", background=CREAM)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure(
            "Title.TLabel",
            background=CREAM,
            foreground=SAGE_DARK,
            font=("TkDefaultFont", 18, "bold"),
        )
        style.configure("Status.TLabel", background=CREAM, foreground=SAGE_DARK)
        style.configure("TLabel", background=PANEL, foreground=INK)
        style.configure("Hint.TLabel", background=PANEL, foreground=SAGE)
        style.configure("Metric.TLabel", background=PANEL, foreground=SAGE_DARK, font=("TkDefaultFont", 13, "bold"))
        style.configure("TEntry", fieldbackground=WHITE, foreground=INK, bordercolor=TAUPE, lightcolor=TAUPE)
        style.configure("TButton", background=SAGE_DARK, foreground=WHITE, borderwidth=0, padding=(14, 8))
        style.map(
            "TButton",
            background=[("disabled", SAGE), ("active", INK), ("pressed", INK)],
            foreground=[("disabled", PANEL), ("active", WHITE), ("pressed", WHITE)],
        )
        style.configure("TNotebook", background=CREAM, borderwidth=0)
        style.configure("TNotebook.Tab", background=TAUPE, foreground=WHITE, padding=(16, 8))
        style.map(
            "TNotebook.Tab",
            background=[("selected", SAGE_DARK), ("active", INK)],
            foreground=[("selected", WHITE), ("active", WHITE)],
        )
        style.configure("Horizontal.TProgressbar", background=SAGE_DARK, troughcolor=PANEL, bordercolor=CREAM)
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, rowheight=26)
        style.configure("Treeview.Heading", background=SAGE_DARK, foreground=WHITE, padding=(8, 6))
        style.map("Treeview", background=[("selected", TAUPE)], foreground=[("selected", INK)])

        root = tk.Frame(self, bg=CREAM, padx=16, pady=16)
        root.pack(fill="both", expand=True)

        header = tk.Frame(root, bg=CREAM)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(
            header,
            text="Local Wi-Fi Speed Tester",
            bg=CREAM,
            fg=SAGE_DARK,
            font=("TkDefaultFont", 18, "bold"),
        ).pack(side="left")
        tk.Label(header, textvariable=self.status_text, bg=CREAM, fg=SAGE_DARK).pack(side="right")

        tab_bar = tk.Frame(root, bg=CREAM)
        tab_bar.pack(fill="x")
        self.content = tk.Frame(root, bg=PANEL, padx=16, pady=16)
        self.content.pack(fill="both", expand=True)

        for tab_name in ("Server", "Client", "History"):
            button = tk.Button(
                tab_bar,
                text=tab_name,
                command=lambda name=tab_name: self.show_tab(name),
                bg=TAUPE,
                fg=WHITE,
                activebackground=SAGE_DARK,
                activeforeground=WHITE,
                relief="flat",
                padx=18,
                pady=8,
                borderwidth=0,
            )
            button.pack(side="left", padx=(0, 4))
            self.tab_buttons[tab_name] = button

            frame = tk.Frame(self.content, bg=PANEL)
            self.tab_frames[tab_name] = frame

        server_tab = self.tab_frames["Server"]
        client_tab = self.tab_frames["Client"]
        history_tab = self.tab_frames["History"]

        self._build_server_tab(server_tab)
        self._build_client_tab(client_tab)
        self._build_history_tab(history_tab)
        self.show_tab("Server")

    def show_tab(self, tab_name: str) -> None:
        """Show one app section and update the tab button colors."""
        for name, frame in self.tab_frames.items():
            if name == tab_name:
                frame.pack(fill="both", expand=True)
                self.tab_buttons[name].configure(bg=SAGE_DARK)
            else:
                frame.pack_forget()
                self.tab_buttons[name].configure(bg=TAUPE)

    def _build_server_tab(self, parent: ttk.Frame) -> None:
        form = ttk.Frame(parent, style="Panel.TFrame")
        form.pack(fill="x")

        ttk.Label(form, text="Bind Host").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.server_host, width=20).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(form, text="Use 0.0.0.0 for other computers", style="Hint.TLabel").grid(row=0, column=2, sticky="w")

        ttk.Label(form, text="Port").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.server_port, width=20).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(form, text="5055 avoids common macOS port 5000 conflicts", style="Hint.TLabel").grid(
            row=1, column=2, sticky="w"
        )

        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.pack(fill="x", pady=12)
        self.start_server_button = ttk.Button(actions, text="Start Server", command=self.start_server)
        self.start_server_button.pack(side="left")
        self.stop_server_button = ttk.Button(actions, text="Stop Server", command=self.stop_server, state="disabled")
        self.stop_server_button.pack(side="left", padx=8)

        self.server_log = tk.Text(parent, height=16, wrap="word", state="disabled")
        self._style_text_widget(self.server_log)
        self.server_log.pack(fill="both", expand=True)
        self._append_server_log("Start the server here, then run the client on another computer.")

    def _build_client_tab(self, parent: ttk.Frame) -> None:
        form = ttk.Frame(parent, style="Panel.TFrame")
        form.pack(fill="x")

        ttk.Label(form, text="Server IP").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.client_ip, width=24).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(
            form,
            text="Example: 10.0.0.20 or 127.0.0.1 for same-computer testing",
            style="Hint.TLabel",
        ).grid(
            row=0, column=2, sticky="w"
        )

        ttk.Label(form, text="Port").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.client_port, width=24).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(form, text="Duration").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.duration, width=24).grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(form, text="Seconds. Use 3 for quick tests, 10 for normal tests", style="Hint.TLabel").grid(
            row=2, column=2, sticky="w"
        )

        ttk.Label(form, text="Location").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.location, width=24).grid(row=3, column=1, sticky="w", padx=8)
        ttk.Label(form, text="Example: Bedroom, Near Router, 5 GHz, Ethernet", style="Hint.TLabel").grid(
            row=3, column=2, sticky="w"
        )

        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.pack(fill="x", pady=12)
        self.run_test_button = ttk.Button(actions, text="Run Test", command=self.run_client_test)
        self.run_test_button.pack(side="left")
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side="left", padx=12)

        metrics = ttk.Frame(parent, style="Panel.TFrame")
        metrics.pack(fill="x", pady=(0, 12))
        self.ping_value = self._metric(metrics, "Ping", 0)
        self.upload_value = self._metric(metrics, "Upload", 1)
        self.download_value = self._metric(metrics, "Download", 2)
        self.stability_value = self._metric(metrics, "Stability", 3)

        ttk.Label(parent, text="Recommendation").pack(anchor="w")
        self.recommendation_text = tk.Text(parent, height=5, wrap="word", state="disabled")
        self._style_text_widget(self.recommendation_text)
        self.recommendation_text.pack(fill="x", pady=(4, 12))

        ttk.Label(parent, text="Detailed Output").pack(anchor="w")
        self.result_text = tk.Text(parent, height=9, wrap="word", state="disabled")
        self._style_text_widget(self.result_text)
        self.result_text.pack(fill="both", expand=True)

    def _build_history_tab(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Refresh History", command=self.load_history).pack(side="left")

        self.history = ttk.Treeview(parent, columns=HISTORY_COLUMNS, show="headings", height=14)
        for column in HISTORY_COLUMNS:
            self.history.heading(column, text=column.replace("_", " ").title())
            self.history.column(column, width=120, anchor="center")
        self.history.column("date", width=170)
        self.history.column("location", width=140)
        self.history.pack(fill="both", expand=True)
        self.load_history()

    def _metric(self, parent: ttk.Frame, label: str, column: int) -> tk.StringVar:
        value = tk.StringVar(value="--")
        frame = ttk.Frame(parent, padding=(0, 0, 24, 0), style="Panel.TFrame")
        frame.grid(row=0, column=column, sticky="w")
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Label(frame, textvariable=value, style="Metric.TLabel").pack(anchor="w")
        return value

    def _style_text_widget(self, widget: tk.Text) -> None:
        widget.configure(
            background=WHITE,
            foreground=INK,
            insertbackground=SAGE_DARK,
            selectbackground=SAGE,
            selectforeground=WHITE,
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
        )

    def start_server(self) -> None:
        try:
            port = int(self.server_port.get())
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a number, such as 5055.")
            return

        self.server = SpeedTestServer(self.server_host.get().strip() or "0.0.0.0", port, self._queue_server_log)
        self.server_thread = threading.Thread(target=self._run_server_worker, daemon=True)
        self.server_thread.start()

        self.start_server_button.configure(state="disabled")
        self.stop_server_button.configure(state="normal")
        self.status_text.set("Server running")

    def _run_server_worker(self) -> None:
        try:
            assert self.server is not None
            self.server.serve_forever()
        except OSError as exc:
            self.message_queue.put(("server_error", str(exc)))

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.stop()
        self.start_server_button.configure(state="normal")
        self.stop_server_button.configure(state="disabled")
        self.status_text.set("Server stopping")

    def run_client_test(self) -> None:
        if self.test_thread is not None and self.test_thread.is_alive():
            return

        try:
            port = int(self.client_port.get())
            duration = float(self.duration.get())
        except ValueError:
            messagebox.showerror("Invalid Test Settings", "Port and duration must be numbers.")
            return

        server_ip = self.client_ip.get().strip()
        location = self.location.get().strip() or "Unknown"
        if not server_ip:
            messagebox.showerror("Missing Server IP", "Enter the IP address shown by the server computer.")
            return

        self.run_test_button.configure(state="disabled")
        self.progress.start(10)
        self.status_text.set("Running test")
        self._set_text(self.result_text, "Running ping test...\n")
        self._set_text(self.recommendation_text, "")

        self.test_thread = threading.Thread(
            target=self._run_client_test_worker,
            args=(server_ip, port, duration, location),
            daemon=True,
        )
        self.test_thread.start()

    def _run_client_test_worker(self, server_ip: str, port: int, duration: float, location: str) -> None:
        try:
            self.message_queue.put(("result_line", "Running ping test...\n"))
            ping_ms = client.ping_test(server_ip, port)

            self.message_queue.put(("result_line", "Running upload test...\n"))
            upload_mbps, upload_samples = client.upload_test(server_ip, port, duration)

            self.message_queue.put(("result_line", "Running download test...\n"))
            download_mbps, download_samples = client.download_test(server_ip, port, duration)

            stability, drops = client.stability_check(upload_samples + download_samples)
            recommendation = client.recommendation(ping_ms, download_mbps, stability)
            client.save_result(location, upload_mbps, download_mbps, ping_ms, stability)

            self.message_queue.put(
                (
                    "test_done",
                    {
                        "server_ip": server_ip,
                        "duration": duration,
                        "ping_ms": ping_ms,
                        "upload_mbps": upload_mbps,
                        "upload_samples": upload_samples,
                        "download_mbps": download_mbps,
                        "download_samples": download_samples,
                        "stability": stability,
                        "drops": drops,
                        "recommendation": recommendation,
                    },
                )
            )
        except Exception as exc:  # The GUI needs to show network errors without crashing.
            self.message_queue.put(("test_error", str(exc)))

    def _show_test_result(self, result: dict[str, object]) -> None:
        upload_samples = result["upload_samples"]
        download_samples = result["download_samples"]
        assert isinstance(upload_samples, list)
        assert isinstance(download_samples, list)
        upload_min, upload_max = client.summarize_speeds(upload_samples)
        download_min, download_max = client.summarize_speeds(download_samples)

        ping_ms = float(result["ping_ms"])
        upload_mbps = float(result["upload_mbps"])
        download_mbps = float(result["download_mbps"])
        stability = str(result["stability"])
        drops = int(result["drops"])

        self.ping_value.set(f"{ping_ms:.2f} ms")
        self.upload_value.set(f"{upload_mbps:.2f} Mbps")
        self.download_value.set(f"{download_mbps:.2f} Mbps")
        self.stability_value.set(stability)
        self._set_text(self.recommendation_text, str(result["recommendation"]))

        details = (
            "Local Wi-Fi Speed Test Results\n"
            "------------------------------\n"
            f"Server IP: {result['server_ip']}\n"
            f"Test duration: {float(result['duration']):g} seconds\n"
            f"Average ping: {ping_ms:.2f} ms\n"
            f"Upload average: {upload_mbps:.2f} Mbps\n"
            f"Upload min/max: {upload_min:.2f} / {upload_max:.2f} Mbps\n"
            f"Download average: {download_mbps:.2f} Mbps\n"
            f"Download min/max: {download_min:.2f} / {download_max:.2f} Mbps\n"
            f"Stability: {stability} ({drops} noticeable drop{'s' if drops != 1 else ''})\n"
            f"Saved to: {client.RESULTS_FILE}\n"
        )
        self._set_text(self.result_text, details)
        self.load_history()

    def load_history(self) -> None:
        for item in self.history.get_children():
            self.history.delete(item)

        path = Path(client.RESULTS_FILE)
        if not path.exists():
            return

        with path.open("r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                values = [row.get(column, "") for column in HISTORY_COLUMNS]
                self.history.insert("", "end", values=values)

    def _queue_server_log(self, message: str) -> None:
        self.message_queue.put(("server_log", message))

    def _append_server_log(self, message: str) -> None:
        self.server_log.configure(state="normal")
        self.server_log.insert("end", message + "\n")
        self.server_log.see("end")
        self.server_log.configure(state="disabled")

    def _append_result_line(self, message: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.insert("end", message)
        self.result_text.see("end")
        self.result_text.configure(state="disabled")

    def _set_text(self, widget: tk.Text, message: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", message)
        widget.configure(state="disabled")

    def _poll_queue(self) -> None:
        while True:
            try:
                event, payload = self.message_queue.get_nowait()
            except queue.Empty:
                break

            if event == "server_log":
                self._append_server_log(str(payload))
                if payload == "Server stopped.":
                    self.start_server_button.configure(state="normal")
                    self.stop_server_button.configure(state="disabled")
                    self.status_text.set("Ready")
            elif event == "server_error":
                self._append_server_log(f"Server error: {payload}")
                self.start_server_button.configure(state="normal")
                self.stop_server_button.configure(state="disabled")
                self.status_text.set("Ready")
                messagebox.showerror("Server Error", str(payload))
            elif event == "result_line":
                self._append_result_line(str(payload))
            elif event == "test_done":
                self.progress.stop()
                self.run_test_button.configure(state="normal")
                self.status_text.set("Ready")
                assert isinstance(payload, dict)
                self._show_test_result(payload)
            elif event == "test_error":
                self.progress.stop()
                self.run_test_button.configure(state="normal")
                self.status_text.set("Ready")
                self._append_result_line(f"\nConnection problem: {payload}\n")
                messagebox.showerror("Connection Problem", str(payload))

        self.after(100, self._poll_queue)

    def _on_close(self) -> None:
        if self.server is not None:
            self.server.stop()
        self.destroy()


if __name__ == "__main__":
    LocalWifiTesterApp().mainloop()
