#!/usr/bin/env python3
import socket
import sys
import time

host, port = sys.argv[1], int(sys.argv[2])
deadline = time.time() + int(sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--timeout" else 60)
while time.time() < deadline:
    with socket.socket() as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            print("READY")
            sys.exit(0)
        except Exception:
            time.sleep(1)
print("TIMEOUT", file=sys.stderr)
sys.exit(1)
