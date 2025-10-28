import os, threading, time
import requests

def start_keepalive():
    url = os.environ.get('KEEPALIVE_URL')
    if not url:
        return
    try:
        interval = int(os.environ.get('KEEPALIVE_INTERVAL','60'))
    except Exception:
        interval = 60
    def loop():
        time.sleep(5)
        while True:
            try:
                requests.get(url, timeout=10)
                print('[keepalive] ping', url)
            except Exception as e:
                print('[keepalive] error', e)
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
