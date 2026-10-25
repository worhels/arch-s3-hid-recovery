"""Live rejection checks. No accepted key reports are sent."""
import argparse
import struct
from client import Client

def rejected(client: Client, path: str, data: bytes | None, code: int) -> None:
    try:
        client.request(path, data)
    except RuntimeError as error:
        if not str(error).startswith(f'HTTP {code}:'):
            raise
    else:
        raise AssertionError(f'{path}: expected HTTP {code}')

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    args = parser.parse_args()
    client = Client(args.host)
    try:
        client.request('/disarm', b'')
        before = client.status()['sequence']
        rejected(client, '/key', struct.pack('>IBB', before + 1, 0, 4), 403)
        client.arm()
        rejected(client, '/key', b'bad', 400)
        rejected(client, '/key', struct.pack('>IBB', before, 0, 4), 409)
        rejected(client, '/key', struct.pack('>IBB', before + 1, 0, 0), 400)
        client.request('/disarm', b'')
        assert client.status()['sequence'] == before
        token = client.config['token']
        client.config['token'] = '0' * 64
        rejected(client, '/status', None, 401)
        client.config['token'] = token
        print('PASS: disarmed, length, sequence, key range and token rejection; no keys sent')
    finally:
        if client.connection:
            client.connection.close()

if __name__ == '__main__':
    main()
