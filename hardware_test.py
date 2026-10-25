"""Visible end-to-end test: HTTPS -> ESP32 -> USB -> Windows text widget."""
import argparse
import json
import queue
import threading
import tkinter as tk
import ctypes
from pathlib import Path
from client import Client, character

parser = argparse.ArgumentParser()
parser.add_argument('--host', required=True)
args = parser.parse_args()
root = tk.Tk()
root.title('ESP32 HID hardware test')
root.geometry('740x260')
# Test application chooses its input layout; does not change persistent Windows settings.
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
if not user32.LoadKeyboardLayoutW('00000409', 1):
    raise ctypes.WinError(ctypes.get_last_error())
tk.Label(root, text='HID test only. Keep this window focused during the test.').pack(pady=10)
entry = tk.Entry(root, font=('Consolas', 16), width=65)
entry.pack(pady=10)
status = tk.StringVar(value='Ready')
tk.Label(root, textvariable=status).pack(pady=10)
expected = 'Arch-HID 123 /bin/bash = + _ : !'
result_path = Path(__file__).resolve().parent / 'hardware-result.json'

def test() -> None:
    user32.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.ActivateKeyboardLayout.restype = ctypes.c_void_p
    layout = user32.LoadKeyboardLayoutW('00000409', 1)
    user32.ActivateKeyboardLayout(layout, 0)
    button.config(state='disabled')
    entry.delete(0, tk.END)
    entry.focus_set()
    root.update_idletasks()
    if root.focus_get() != entry:
        status.set('Could not focus the test field; click it and retry.')
        button.config(state='normal')
        return
    status.set('Testing physical USB input...')
    result_queue: queue.Queue[str | None] = queue.Queue()
    stop = threading.Event()
    worker_active = threading.Event()

    def monitor_focus() -> None:
        if not worker_active.is_set():
            return
        if root.focus_get() != entry:
            stop.set()
        root.after(25, monitor_focus)

    def worker() -> None:
        client = None
        error = None
        worker_active.set()
        try:
            client = Client(args.host)
            current = client.status()
            if current['leds'] & 2:
                raise RuntimeError('Caps Lock is on; turn it off and retry')
            client.arm()
            for char in expected:
                if stop.is_set():
                    raise RuntimeError('Focus lost; stopped')
                client.key(*character(char))
        except Exception as exc:
            error = str(exc)
        finally:
            if client is not None:
                try:
                    client.request('/disarm', b'')
                except Exception as exc:
                    if error is None:
                        error = 'Could not disarm device; unplug USB if a key is stuck: ' + str(exc)
                if client.connection:
                    try:
                        client.connection.close()
                    except OSError as exc:
                        if error is None:
                            error = 'Could not close HTTPS connection: ' + str(exc)
            worker_active.clear()
            result_queue.put(error)

    def finish_when_ready() -> None:
        try:
            error = result_queue.get_nowait()
        except queue.Empty:
            root.after(25, finish_when_ready)
            return
        received = entry.get()
        passed = error is None and received == expected
        result_path.write_text(json.dumps({'passed': passed, 'expected': expected,
            'received': received, 'error': error}, indent=2), encoding='utf-8')
        status.set('PASS: exact USB input received' if passed else 'FAIL: ' + (error or 'layout/input mismatch'))
        button.config(state='normal')

    threading.Thread(target=worker, daemon=True).start()
    root.after(25, monitor_focus)
    root.after(25, finish_when_ready)

button = tk.Button(root, text='Start USB test', command=test)
button.pack(pady=10)
root.mainloop()
