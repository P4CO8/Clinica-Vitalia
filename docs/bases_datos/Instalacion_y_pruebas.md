# Instalación y pruebas

1. Instalar dependencias con `python -m pip install -r requirements.txt`.
2. Configurar `.env` con `POSTGRES_URL` y `SECRET_KEY`.
3. Instalar o actualizar el esquema mediante `db/postgres/instalar.sql` y
   `python actualizar_sql.py`.
4. Iniciar la aplicación con `python run.py`.
5. Ejecutar `python -m pytest -q`.

La validación de MongoDB se ejecuta con `db/mongo/01_modelo.js` y
`db/mongo/02_pruebas_crud.js` cuando el motor documental esté disponible.
