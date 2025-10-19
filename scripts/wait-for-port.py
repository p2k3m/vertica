#!/usr/bin/env python3
"""Wait until a TCP port on a host is accepting connections."""

import argparse
import socket
import sys
import time


def wait_for_port(host: str, port: int, timeout: float, interval: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(interval)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    try:
        wait_for_port(args.host, args.port, args.timeout, args.interval)
    except TimeoutError as exc:  # pragma: no cover - CLI utility
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
