import time
from datetime import datetime

from config import SCRAPER_INTERVAL_MINUTES
from run_scraper import run


def main():
    print("Actualizador periodico iniciado.")
    print("Presiona Ctrl+C para detenerlo.")

    while True:
        print(f"Ejecutando scraper: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        run()
        time.sleep(SCRAPER_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
