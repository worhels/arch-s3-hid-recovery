"""Local broadcast discovery; every candidate is verified by pinned TLS."""
import socket
import time
import argparse
from client import Client

def discover(broadcast: str = '255.255.255.255') -> list[str]:
    candidates: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.bind(('', 0))
        for _ in range(3):
            sock.sendto(b'ARCH-HID/1', (broadcast, 4210))
            until = time.monotonic() + 1
            while time.monotonic() < until:
                try:
                    data, address = sock.recvfrom(64)
                    if data == b'ARCH-HID/1':
                        candidates.add(address[0])
                except TimeoutError:
                    pass
    verified = []
    for host in sorted(candidates):
        client = Client(host)
        try:
            client.status()
            verified.append(host)
        except (OSError, RuntimeError):
            continue
        finally:
            if client.connection:
                client.connection.close()
    return verified

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--broadcast', default='255.255.255.255')
    args = parser.parse_args()
    hosts = discover(args.broadcast)
    print('\n'.join(hosts) if hosts else 'No verified device found; check Wi-Fi/client isolation and USB power.')
