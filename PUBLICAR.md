# Como compartir la pagina con tus companeros

Ahora mismo la pagina funciona en tu computador con:

```text
http://127.0.0.1:5000
```

Ese link solo sirve en tu computador. Para que tus companeros la abran desde sus casas, necesitas publicarla en internet.

## Forma recomendada

Usa GitHub para subir el proyecto y luego un hosting para publicarlo.

El camino es:

```text
Tu carpeta del proyecto
        |
GitHub
        |
Hosting en internet
        |
Link publico para tus companeros
```

## Archivos preparados para publicar

Ya tienes estos archivos:

- `app.py`: muestra la pagina web.
- `run_scraper.py`: actualiza los precios.
- `start.py`: actualiza precios y luego prende la pagina.
- `Procfile`: le dice al hosting como iniciar el proyecto.
- `requirements.txt`: lista las librerias necesarias.

## Opcion sencilla: Render

1. Crea una cuenta en GitHub.
2. Crea un repositorio nuevo.
3. Sube todos los archivos de esta carpeta al repositorio.
4. Crea una cuenta en Render.
5. En Render, crea un nuevo servicio tipo Web Service.
6. Conecta tu repositorio de GitHub.
7. Usa esta configuracion:

```text
Build Command:
pip install -r requirements.txt

Start Command:
python start.py
```

8. Render te dara un link parecido a:

```text
https://tu-proyecto.onrender.com
```

Ese link si lo pueden abrir tus companeros desde sus casas.

## Ruta para trabajar desde tu PC

Si descargaste el proyecto en esta carpeta, entra con PowerShell:

```powershell
cd "C:\Users\sebas\Documents\Codex\2026-05-19\necesito-verificar-cada-uno-de-los\preciomed-main"
```

Luego ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_scraper.py
python app.py
```

Abre la pagina local:

```text
http://127.0.0.1:5000
```

Cuando hagas cambios y tengas `git` instalado:

```powershell
git add .
git commit -m "Mejorar validacion de productos y descuentos"
git push
```

Render tomara los cambios desde GitHub y publicara otra vez el servicio.

## Variables importantes en Render

En Render revisa que el servicio tenga:

```text
Build Command: pip install -r requirements.txt
Start Command: python start.py
```

Si Render te asigna un puerto automatico, no lo cambies: la app ya lee la variable `PORT`.

## Nota importante

En un hosting gratuito, la base de datos SQLite puede reiniciarse si el servidor se apaga. Para una entrega universitaria esta version sirve como prototipo. Para una version mas profesional, el siguiente paso seria usar una base de datos en la nube como PostgreSQL.
