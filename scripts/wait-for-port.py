#!/usr/bin/env python3
import socket
import sys
import time

host, port, timeout = sys.argv[1], int(sys.argv[2]), int(sys.argv[4]) if len(sys.argv) > 4 else 60
start = time.time()
while time.time() - start < timeout:
    try:
        with socket.create_connection((host, port), 2):
            sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(1)
