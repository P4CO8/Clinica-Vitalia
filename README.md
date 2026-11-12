# Clínica Vitalia

Sistema web de gestión clínica desarrollado con Flask y PostgreSQL. Incluye
usuarios y roles, pacientes, agenda de citas, atención clínica, comunicación
interna y facturación.

## Ejecución

```powershell
python -m pip install -r requirements.txt
python configurar.py
python run.py
```

La configuración de PostgreSQL se define en `.env`. El esquema se instala con
`db/postgres/instalar.sql` y las actualizaciones se aplican con
`python actualizar_sql.py`.

## Pruebas

```powershell
python -m pytest -q
```

Los diagramas conceptual y relacional se encuentran en `docs/bases_datos`.
