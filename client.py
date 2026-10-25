"""Authenticated, certificate-pinned HID client; standard library only."""
import argparse
import hashlib
import hmac
import http.client
import json
import re
import ssl
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_RESPONSE_BYTES = 4096
KEYS = {"enter": 40, "esc": 41, "backspace": 42, "tab": 43, "space": 44,
        "home": 74, "pageup": 75, "delete": 76, "end": 77, "pagedown": 78,
        "right": 79, "left": 80, "down": 81, "up": 82}
KEYS.update({f"f{i}": 57 + i for i in range(1, 13)})

def character(char: str) -> tuple[int, int]:
    if len(char) != 1:
        raise ValueError("Expected one character")
    if 'a' <= char <= 'z':
        return 0, ord(char) - 93
    if 'A' <= char <= 'Z':
        return 2, ord(char) - 61
    if char in '1234567890':
        return 0, 30 + '1234567890'.index(char)
    plain = "-=[]\\;'/`,. "
    shifted = '_+{}|:"?~<> '
    codes = [45, 46, 47, 48, 49, 51, 52, 56, 53, 54, 55, 44]
    if char in plain:
        return 0, codes[plain.index(char)]
    if char in shifted:
        return 2, codes[shifted.index(char)]
    if char in '!@#$%^&*()':
        return 2, 30 + '!@#$%^&*()'.index(char)
    raise ValueError("Only printable US ASCII is supported; select US layout")

def chord(value: str) -> tuple[int, int]:
    parts = value.lower().split('+')
    modifier = 0
    for part in parts[:-1]:
        modifier |= {"ctrl": 1, "shift": 2, "alt": 4, "gui": 8}[part]
    key = parts[-1]
    if key in KEYS:
        return modifier, KEYS[key]
    shift, code = character(key)
    return modifier | shift, code

class Client:
    def __init__(self, host: str, config: Path = ROOT / 'private/client.json'):
        self.host = host
        self.config = json.loads(config.read_text(encoding='utf-8'))
        self.sequence: int | None = None
        self.connection: http.client.HTTPSConnection | None = None

    def connect(self) -> http.client.HTTPSConnection:
        # Pin DER SHA256 before sending HTTP headers or credentials.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = http.client.HTTPSConnection(self.host, timeout=8, context=context)
        conn.connect()
        assert conn.sock is not None
        digest = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(digest, self.config['fingerprint']):
            conn.close()
            raise RuntimeError('Certificate mismatch: no credentials or keys sent')
        return conn

    def request(self, path: str, data: bytes | None = None) -> str:
        try:
            if self.connection is None or self.connection.sock is None:
                self.connection = self.connect()
            self.connection.request('GET' if data is None else 'POST', path, body=data,
                headers={'Authorization': 'Bearer ' + self.config['token'],
                         'Content-Type': 'application/octet-stream'})
            response = self.connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError('Device response exceeds the size limit')
            content = raw.decode('utf-8')
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}: {content}')
            return content
        except Exception:
            if self.connection:
                self.connection.close()
            self.connection = None
            self.sequence = None
            raise  # Never retry ambiguous input automatically.

    def status(self) -> dict:
        try:
            result = json.loads(self.request('/status'))
        except json.JSONDecodeError:
            raise RuntimeError('Device returned invalid status JSON') from None
        if not isinstance(result, dict):
            raise RuntimeError('Device returned an invalid status object')
        if (type(result.get('usb')) is not bool
                or type(result.get('armed')) is not bool
                or type(result.get('sequence')) is not int
                or not 0 <= result['sequence'] <= 0xFFFFFFFF
                or type(result.get('leds')) is not int
                or not 0 <= result['leds'] <= 0xFF):
            raise RuntimeError('Device returned an invalid status object')
        self.sequence = result['sequence']
        return result

    def arm(self) -> None:
        self.status()
        self.request('/arm', b'')

    def key(self, modifier: int, code: int) -> None:
        if self.sequence is None:
            raise RuntimeError('Run status/arm first; inspect the screen after failures')
        next_sequence = self.sequence + 1
        self.request('/key', struct.pack('>IBB', next_sequence, modifier, code))
        self.sequence = next_sequence

    def text(self, value: str) -> None:
        events = [character(c) for c in value]  # Validate entire text before any input.
        for event in events:
            self.key(*event)

    def press(self, value: str) -> None:
        self.key(*chord(value))

    def line(self, value: str) -> None:
        self.text(value)
        self.press('enter')

def confirm(message: str) -> None:
    if input(message + '\nType YES when confirmed: ').strip() != 'YES':
        raise RuntimeError('Stopped without proceeding')

def recover(client: Client, loader: str, username: str) -> None:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,31}', username):
        raise ValueError('Invalid username')
    confirm('Laptop: the correct Arch boot entry is selected in the boot menu?')
    client.arm()
    client.text('e')
    if loader == 'grub':
        confirm('Editor visible? Use the interactive client arrows to select the linux/linuxefi line, '
                'then resume here. Do NOT select initrd. Cursor on kernel line?')
        client.arm()
        client.press('end')
    else:
        confirm('Kernel command-line editor visible? If editing is disabled, STOP.')
        client.arm()
        client.press('end')
    confirm('Cursor at end of the complete kernel line; no existing init= parameter?')
    client.arm()
    client.text(' init=/bin/bash')
    confirm('Screen shows correct appended init=/bin/bash, existing root/crypt parameters intact?')
    client.arm()
    client.press('ctrl+x' if loader == 'grub' else 'enter')
    confirm('Unlock encryption locally if requested. Root bash prompt visible (not login/initramfs)?')
    client.arm()
    client.line('export HISTFILE=/dev/null')
    client.line('mount -n -o remount,rw / && passwd ' + username)
    confirm('Enter the new password twice ON THE LAPTOP. Screen confirms password updated and bash prompt returned?')
    client.arm()
    client.line('sync && mount -n -o remount,ro / && /sbin/reboot -f')
    print('Wait for normal boot; log in locally. Then run the ssh-setup command.')

def ssh_setup(client: Client) -> None:
    confirm('Normal Arch boot completed, logged in as recovered user, terminal focused with US layout?')
    client.arm()
    client.line('sudo -v')
    confirm('Enter your password locally if sudo asks. Shell prompt returned without errors?')
    client.arm()
    client.line('pacman -Q openssh')
    confirm('openssh package/version displayed? If missing, STOP; install separately without partial upgrades.')
    client.arm()
    client.line('sudo ssh-keygen -A && sudo /usr/bin/sshd -t && sudo systemctl enable --now sshd')
    confirm('No errors?')
    client.arm()
    client.line('systemctl is-active sshd; ip -br address; sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub')
    print('Report LAN IP and host-key fingerprint; verify it on first Windows SSH connection.')

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('command', choices=['status', 'interactive', 'recover', 'ssh-setup', 'disarm'])
    parser.add_argument('--loader', choices=['grub', 'systemd-boot'])
    parser.add_argument('--user')
    args = parser.parse_args()
    client = Client(args.host)
    try:
        if args.command == 'status':
            print(client.status())
        elif args.command == 'disarm':
            print(client.request('/disarm', b''))
        elif args.command == 'recover':
            if not args.loader or not args.user:
                parser.error('recover requires --loader and --user')
            recover(client, args.loader, args.user)
        elif args.command == 'ssh-setup':
            ssh_setup(client)
        else:
            print('Commands: status, arm, disarm, key ctrl+x, text TEXT, line COMMAND, quit. US layout only.')
            while True:
                value = input('hid> ')
                operation, _, argument = value.partition(' ')
                if operation == 'quit':
                    break
                if operation == 'status':
                    print(client.status())
                elif operation == 'arm':
                    client.arm()
                elif operation == 'disarm':
                    client.request('/disarm', b'')
                elif operation == 'key':
                    client.press(argument)
                elif operation == 'text':
                    client.text(argument)
                elif operation == 'line':
                    client.line(argument)
                else:
                    print('Unknown command')
    finally:
        if args.command != 'status':
            try:
                client.request('/disarm', b'')
            except Exception:
                print('Could not disarm over network; unplug USB if a key is stuck.')
        if client.connection:
            client.connection.close()

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error)) from None
