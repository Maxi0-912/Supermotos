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

Ahí ves los 3.088 productos, las cotizaciones que entran por el bot, y la
pantalla "Actualizar inventario desde Celeste" para subir el Excel.

## 3. Ver la página web + bot
Con el backend corriendo (paso 1), abre directamente http://127.0.0.1:8000/ —
Django sirve ahí mismo la página y el bot (`web_frontend.html` +
`static/js/bot.js`), en el mismo puerto que la API, sin CORS ni Live Server.
El bot ya consulta el inventario REAL: prueba escribirle
"pastillas cb160", "filtro aire xr150", "bateria", "kit arrastre".

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
