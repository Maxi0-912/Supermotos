# SuperMotos La 4ta — Backend (Django + DRF)

Backend para la página web y el bot del almacén, con inventario sincronizado
desde **Celeste MIPYME** vía exportación a Excel.

## Arranque local
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
- Panel de administración: http://127.0.0.1:8000/admin/
- API: http://127.0.0.1:8000/api/productos/

## Importar el inventario de Celeste
En Celeste: **Productos → botón Excel** para exportar. Luego, cualquiera de las dos vías:

1. **Panel web (para la dueña):** Admin → Importaciones de inventario → `subir/`
   (pantalla "Actualizar inventario desde Celeste")
2. **Terminal (para ti):**
```bash
python manage.py importar_inventario export_celeste.xlsx
python manage.py importar_inventario export_celeste.xlsx --desactivar-faltantes
```

El importador:
- Usa el **Código de Celeste** como llave (crea o actualiza, nunca duplica)
- Detecta columnas por nombre aunque cambien de orden (ver ALIAS en `tienda/importador.py`)
- Convierte precios colombianos ("390.000") a números
- Extrae la **referencia Honda** y los **modelos compatibles** desde la descripción
- El stock negativo se guarda tal cual pero la web/bot muestran 0

⚠️ **Cuando llegue el Excel real de Ana:** probarlo con
`python manage.py importar_inventario archivo_real.xlsx` y ajustar `ALIAS`
en `tienda/importador.py` si alguna columna no se detecta.

## Endpoints del API
| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/productos/?buscar=pastillas+cb160&con_stock=1` | Buscador del bot y catálogo |
| GET | `/api/productos/?modelo=CB160F` | Filtro por moto |
| POST | `/api/cotizaciones/` | El bot guarda cotizaciones |
| POST | `/api/citas/` | El bot agenda citas |
| POST | `/api/importar-inventario/` | Subida del Excel (solo admin) |

Ejemplo de cotización (POST JSON):
```json
{"nombre_cliente":"Carlos","telefono":"3001234567","origen":"web",
 "items":[{"producto_id":1,"cantidad":1}]}
```

## Frontend
`web_frontend.html` es la página con el bot. Para conectarla al backend,
editar la primera línea del script:
```js
const API_URL = "https://tu-backend.up.railway.app";
```
Con `API_URL = ""` funciona en modo demo con datos de ejemplo.

## Despliegue en Railway (igual que TuTaller)
1. Subir este repo a GitHub y crear proyecto en Railway con PostgreSQL
2. Variables: `SECRET_KEY`, `DATABASE_URL` (automática), `CSRF_ORIGIN`
3. Añadir a settings para producción: whitenoise + dj_database_url (mismo patrón que BackendFull)
4. `python manage.py createsuperuser` en la consola de Railway

## Pendientes cuando llegue el Excel real
- [ ] Validar mapeo de columnas con el archivo real de Ana
- [ ] Cargar los 3.062 productos y revisar categorías
- [ ] Definir rutina de actualización con la dueña (diaria/semanal)
- [ ] Fase 2: conectar WhatsApp Cloud API a estos mismos endpoints
