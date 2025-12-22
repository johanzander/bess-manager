#!/usr/bin/env python3
"""
File watcher for hot-reloading the backend server during development.
This script monitors for changes to Python files and restarts the
FastAPI application when changes are detected.
"""

import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Colors for console output
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
ENDC = "\033[0m"

# Configuration
WATCHED_DIRECTORIES = ["."]
WATCHED_EXTENSIONS = [".py"]
PYTHON_EXECUTABLE = sys.executable
INITIAL_WAIT_TIME = 2  # seconds
DEBOUNCE_TIME = 2.0  # seconds - increased to reduce sensitivity

# Keep track of the server process
server_process = None
last_change_time = 0


class ChangeHandler(FileSystemEventHandler):
    """Handle file system change events."""

    def on_modified(self, event):
        """React to file modifications (not access, only actual changes)."""
        global last_change_time, server_process

        # Get the filename from the path
        filename = os.path.basename(event.src_path)

        # Only restart for user-initiated changes, not system/temp files
        # Skip app.py and other problematic files that might cause restart loops
        if (filename == "app.py") and not os.environ.get("FORCE_RELOAD_APP"):
            print(
                f"{YELLOW}Ignoring auto-detected change in {filename} to prevent restart loops{ENDC}"
            )
            return

        # Ignore directory changes and temp files
        if (
            event.is_directory
            or event.src_path.endswith(".pyc")
            or event.src_path.endswith("~")
            or "__pycache__" in event.src_path
            or ".git" in event.src_path
        ):
            return

        # Check if the file has an extension we care about
        _, ext = os.path.splitext(event.src_path)
        if ext not in WATCHED_EXTENSIONS:
            return

        # Implement a simple debounce
        current_time = time.time()
        if current_time - last_change_time < DEBOUNCE_TIME:
            return

        last_change_time = current_time

        print(f"{YELLOW}Change detected in {event.src_path}{ENDC}")
        restart_server()


def start_server():
    """Start the uvicorn server"""
    global server_process

    cmd = ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
    print(f"Starting server: {' '.join(cmd)}")

    server_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
    )

    # Print the process ID
    print(f"{GREEN}Server started with PID: {server_process.pid}{ENDC}")

    # Start a thread to stream the output
    def stream_output():
        for line in server_process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

    import threading

    output_thread = threading.Thread(target=stream_output)
    output_thread.daemon = True
    output_thread.start()


def restart_server():
    """Restart the FastAPI server."""
    global server_process

    if server_process:
        print(f"{YELLOW}Stopping server (PID: {server_process.pid})...{ENDC}")

        # Try to terminate gracefully first
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"{RED}Server didn't terminate gracefully, killing it...{ENDC}")
            server_process.kill()

        print(f"{GREEN}Server stopped{ENDC}")

    # Start the server again
    start_server()


def main():
    """Main function to run the watcher."""
    print(f"{BLUE}==== FastAPI Development Hot-Reload Watcher ===={ENDC}")
    print(f"{BLUE}Watching directories: {', '.join(WATCHED_DIRECTORIES)}{ENDC}")
    print(f"{BLUE}Watching file types: {', '.join(WATCHED_EXTENSIONS)}{ENDC}")

    # Start the server initially
    time.sleep(INITIAL_WAIT_TIME)  # Give time for the Docker container to fully start
    start_server()

    # Set up the file watcher
    event_handler = ChangeHandler()
    observer = Observer()

    for directory in WATCHED_DIRECTORIES:
        if os.path.exists(directory):
            observer.schedule(event_handler, directory, recursive=True)
            print(f"{GREEN}Watching {directory}{ENDC}")
        else:
            print(f"{RED}Directory not found: {directory}{ENDC}")

    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"{YELLOW}Stopping file watcher...{ENDC}")
        if server_process:
            server_process.terminate()
        observer.stop()

    observer.join()
    if server_process:
        server_process.wait()
    print(f"{BLUE}File watcher and server stopped{ENDC}")


if __name__ == "__main__":
    main()
