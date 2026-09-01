# Cómo probar el sistema con el inventario real de Ana

El proyecto ya viene con los **3.088 productos reales** de SuperMotos La 4ta
importados en la base de datos (db.sqlite3). Puedes verlo funcionando de una:

## 1. Levantar el backend
```bash
cd supermotos_backend
pip install -r requirements.txt
python manage.py runserver
```

## 2. Ver el panel de administración (lo que usará Ana)
Abre http://127.0.0.1:8000/admin/
- Usuario: **admin**
- Contraseña: la que hayas definido con `python manage.py changepassword admin`
  (la contraseña de demo anterior quedó expuesta públicamente y ya no es
  válida — ver aviso de seguridad en el README).

Ahí ves los 3.088 productos, las cotizaciones y citas que entran por el bot,
y la pantalla "Actualizar inventario desde Celeste" para subir el Excel.

## 3. Ver la página web + bot
Abre `web_frontend.html` con Live Server (o doble clic).
El bot ya consulta el inventario REAL: prueba escribirle
"pastillas cb160", "filtro aire xr150", "bateria", "kit arrastre".

> Nota: como el backend corre en http://127.0.0.1:8000, si abres el HTML
> directamente (file://) el navegador puede bloquear las peticiones por CORS.
> Con Live Server (http://127.0.0.1:5500) funciona sin problema porque
> CORS_ALLOW_ALL_ORIGINS está activo en desarrollo.

## 4. Actualizar el inventario cuando Ana exporte de Celeste
En Celeste: Productos -> botón Excel. Luego:
```bash
python manage.py importar_inventario INVENTARIO.xlsx
```
o desde el panel: Importaciones de inventario -> subir/

## Resultados del parseo con el archivo real (INVENTARIO.xlsx, 3.088 productos)
- 90% con referencia Honda/proveedor extraída automáticamente
- 48% con modelos compatibles detectados
- 878 productos con stock disponible
- Precios colombianos convertidos correctamente
- Stock negativo (34 casos) se guarda pero se muestra 0 en la web
