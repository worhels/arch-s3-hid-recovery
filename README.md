# Arch S3 HID Recovery

A small, local-only recovery keyboard for an ESP32-S3 with native USB. It exposes a USB HID keyboard and accepts authenticated, certificate-pinned commands from a Windows client over the same trusted Wi-Fi network.

This project is for recovering a computer you own or are authorized to administer. It does not bypass disk encryption: you must already know the LUKS/recovery key if the system asks for it. The HID device cannot see the laptop screen, so the operator must verify each boot/recovery screen.

## What is included

- `firmware/`: ESP-IDF application using Espressif's TinyUSB component.
- `client.py`: authenticated Windows/Python controller; uses the Python standard library.
- `provision.py`: creates local Wi-Fi credentials, a random API token and a self-signed TLS certificate.
- `discover.py`: finds the device on the LAN; TLS pinning verifies candidates.
- `hardware_test.py`, `test_client.py`, `test_device.py`: visible USB test and client/device rejection checks.
- `build.ps1`: builds firmware; flashing requires an explicit switch, a port, provisioned credentials, and a local flash backup.

Secrets and generated files are created under `private/` and ignored by Git. Never publish `private/`, firmware build output, a flash dump, or a provisioned firmware binary: credentials and the TLS private key are embedded in the firmware image.

## Requirements

- ESP32-S3 board with native USB device support (not a USB-to-UART-only connector). Check the board pinout and flash size first.
- ESP-IDF 6.1.0 for ESP32-S3, with `idf.py` available in PowerShell.
- Windows 10/11, Python 3.10+, and a data-capable USB cable.
- A 2.4 GHz Wi-Fi network reachable from the Windows PC and laptop. Client isolation may block communication.

The checked-in `dependencies.lock` pins the Espressif TinyUSB components. Component sources are fetched by ESP-IDF from Espressif Component Registry during build; they are not vendored here.

## Build and provision

Run from the repository root in an ESP-IDF PowerShell environment:

```powershell
python -m pip install -r requirements.txt
python .\provision.py --gui
.\build.ps1
```

The provisioning dialog writes `private/credentials.h`, `private/client.json`, `private/servercert.pem`, and `private/prvtkey.pem`. Keep this directory private. Use a dedicated trusted Wi-Fi network; do not add router port forwarding or expose the API to the Internet.

To test compilation without real Wi-Fi credentials, run `python .\provision.py --build-only` and then run `.\build.ps1`. Build-only credentials are not suitable for recovery or flashing.

Before flashing any board, inspect its existing layout and save a full flash dump locally. Do not erase the chip. Flashing rewrites firmware and the configured partition table, so only use this setup on a board whose contents you are willing and able to restore. The helper refuses to flash unless it sees both the local `private/esp32-original.bin` backup and real provisioned credentials:

```powershell
python -m esptool --port COMx read-flash 0 ALL .\private\esp32-original.bin
.\build.ps1 -Flash -Port COMx
```

A backup file is sensitive and must stay outside the public repository.

## Connect and operate

1. Connect the ESP32 to Windows over its native USB port and flash the board. Keep it powered.
2. Move the same USB connection to the target laptop. Both devices must be on the provisioned Wi-Fi network.
3. Discover the ESP32 or use its DHCP address from the router:

```powershell
python .\discover.py
python .\client.py --host DEVICE_IP status
python .\client.py --host DEVICE_IP interactive
```

The interactive controller supports `status`, `arm`, `disarm`, `key`, `text`, and `line`. It sends only printable US-ASCII. Use `disarm` when finished and unplug the board after recovery. Never send a new password through this controller or chat; type it locally on the laptop.

The recovery flow needs a physical operator to enter/confirm the boot menu and inspect the screen. On a standard, unencrypted Arch install, a one-time GRUB edit can append `init=/bin/bash`; remount the root filesystem read-write and use `passwd USERNAME`. Then sync, remount read-only and reboot. Do not change the saved GRUB configuration. This procedure does not work around a GRUB/UEFI password, an unknown disk-encryption key, or an immutable signed boot chain.

## Security model and limitations

- HTTPS is required; the client pins the self-signed certificate before sending its bearer token.
- The API is disabled for keyboard input until explicitly armed, and automatically disarms after a short interval.
- Requests use a strictly increasing sequence number. On ambiguous network errors the client does not retry keystrokes.
- UDP discovery only reports candidates; it is not authentication.
- Anyone with physical access to an armed device can cause keystrokes. Keep the device physically controlled and never expose it beyond a trusted LAN.
- A successful HTTP response means a HID report was submitted, not that the OS accepted a command.

## License

The project code is MIT licensed. Third-party Espressif/TinyUSB components retain their own licenses and are fetched separately.
