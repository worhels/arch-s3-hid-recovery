"""Generate local credentials. Never print credentials or put them in argv."""
import argparse
import datetime as dt
import getpass
import json
import secrets
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent

def configure(ssid: str, password: str) -> None:
    private = ROOT / "private"
    private.mkdir(exist_ok=True)
    if not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password.encode()) <= 63:
        raise ValueError("SSID must be 1..32 bytes; WPA password 8..63 bytes")
    # Preserve identity across Wi-Fi changes.
    if not (private / "client.json").exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "arch-recovery")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=3650))
                .sign(key, hashes.SHA256()))
        (private / "servercert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (private / "prvtkey.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (private / "client.json").write_text(json.dumps({"token": secrets.token_hex(32),
            "fingerprint": cert.fingerprint(hashes.SHA256()).hex()}), encoding="utf-8")
    config = json.loads((private / "client.json").read_text())
    def cstr(value: str) -> str:
        return '"' + ''.join('\\%03o' % b for b in value.encode()) + '"'
    (private / "credentials.h").write_text(
        "#pragma once\n#define WIFI_SSID " + cstr(ssid) +
        "\n#define WIFI_PASSWORD " + cstr(password) +
        '\n#define API_TOKEN "' + config["token"] + '"\n', encoding="ascii")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true", help="Offline test credentials; do not flash")
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    if args.build_only and (ROOT / 'private/provisioned').exists():
        raise SystemExit('Refusing to replace provisioned Wi-Fi with build-only settings')
    if args.gui:
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        window = tk.Tk()
        window.withdraw()
        ssid = simpledialog.askstring("ESP32 Wi-Fi", "Имя домашней сети Wi-Fi (2.4 GHz):", parent=window)
        if ssid is None:
            raise SystemExit("Cancelled")
        password = simpledialog.askstring("ESP32 Wi-Fi", "Пароль Wi-Fi (не отправляется в чат):", show="*", parent=window)
        if password is None:
            raise SystemExit("Cancelled")
        try:
            configure(ssid, password)
            (ROOT / 'private/provisioned').touch()
        except ValueError as error:
            messagebox.showerror("Configuration", str(error), parent=window)
            raise SystemExit(1)
        window.destroy()
    else:
        configure("UNPROVISIONED" if args.build_only else input("Wi-Fi SSID (2.4 GHz): "),
                  secrets.token_hex(16) if args.build_only else getpass.getpass("Wi-Fi password: "))
        if not args.build_only:
            (ROOT / 'private/provisioned').touch()
    print("Local credentials prepared. Values are not logged.")
