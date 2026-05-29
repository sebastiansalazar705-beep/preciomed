# Publicar PrecioMed en Render

Este proyecto ya esta preparado para desplegarse como Web Service en Render.

## Pasos

1. Sube el repositorio a GitHub.
2. Entra a Render.
3. Selecciona `New +`.
4. Selecciona `Web Service`.
5. Conecta tu repositorio de GitHub.
6. Usa esta configuracion:

```text
Runtime:
Python

Build Command:
pip install -r requirements.txt

Start Command:
uvicorn app:app --host 0.0.0.0 --port $PORT
```

El archivo `render.yaml` ya contiene esta configuracion.

## Variables de entorno recomendadas

```text
PRECIOMED_USERNAME=admin
PRECIOMED_PASSWORD_HASH=<hash bcrypt de tu contrasena>
PRECIOMED_SECRET_KEY=<clave larga aleatoria>
```

En Render debes configurar `PRECIOMED_PASSWORD_HASH`. Para desarrollo local puedes usar `PRECIOMED_DEV_PASSWORD` en tu entorno.

## Error comun: No open ports detected

Ese error aparece cuando Render no detecta un servidor escuchando el puerto correcto.

PrecioMed ya esta configurado para escuchar:

```text
0.0.0.0:$PORT
```

Por eso debes usar el comando con `uvicorn` indicado arriba.
