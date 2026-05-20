from app import run_server
from run_scraper import run


if __name__ == "__main__":
    print("Actualizando precios antes de iniciar la pagina...")
    run()
    run_server()
