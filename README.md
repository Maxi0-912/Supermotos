# SuperMotos La 4ta — Backend (Django + DRF)

Backend para la página web y el bot del almacén, con inventario sincronizado
desde **Celeste MIPYME** vía exportación a Excel.

## ⚠️ Aviso de seguridad
Un commit anterior de este repo expuso por error `db.sqlite3`, credenciales
de demo y la `SECRET_KEY` en texto plano. Ese historial fue reescrito y las
credenciales/clave quedaron rotadas — pero si clonaste el repo antes de esta
limpieza, esos valores viejos deben tratarse como comprometidos. Ver
`SECRET_KEY` en variable de entorno (abajo) y `.gitignore` para lo que nunca
debe subirse.

## Configuración
La `SECRET_KEY` real vive en la variable de entorno `SECRET_KEY` (nunca en
el código). En local puedes exportarla en tu shell o crear un `.env` (no se
sube, está en `.gitignore`); en Railway se define en sus *Variables*.

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
| GET | `/api/config/` | Datos de contacto del almacén (WhatsApp, teléfono, dirección) |
| POST | `/api/cotizaciones/` | El bot guarda cotizaciones |
| POST | `/api/importar-inventario/` | Subida del Excel (solo admin) |

Ejemplo de cotización (POST JSON):
```json
{"nombre_cliente":"Carlos","telefono":"3001234567","origen":"web",
 "items":[{"producto_id":1,"cantidad":1}]}
```

## Frontend
`web_frontend.html` (con su lógica en `static/js/bot.js`) la sirve Django en
la raíz ("/"), en el mismo puerto que la API — no hace falta editar ninguna
URL a mano ni en desarrollo ni en producción: `API_URL = ""` en `bot.js`
significa "mismo origen", así que las llamadas a `/api/...` siempre apuntan
solas al dominio donde esté corriendo el backend (Railway incluido).
Para usar datos de ejemplo sin backend, cambiar `USAR_DEMO` a `true` en
`static/js/bot.js`.

Los datos de contacto (WhatsApp, teléfono fijo, dirección) NO están en el
HTML: salen de `/api/config/` → **Admin → Configuración del sitio**, una sola
fuente para el bot, el pie de página y la sección de taller. Si el WhatsApp
no está bien cargado, el sitio esconde el botón y muestra el teléfono/dirección
en su lugar (nunca un enlace a un número inventado).

## Antes de publicar (checklist obligatorio)
- [ ] **Reemplazar el número de pruebas.** En **Admin → Configuración del
  sitio**, cambiar `whatsapp_asesor` (hoy `573167599778`, número de pruebas)
  por el **WhatsApp exclusivo del almacén**. Un número de pruebas en producción
  manda clientes reales al teléfono equivocado y, con dos vendedores atendiendo,
  nadie se entera. El campo valida 10–15 dígitos con indicativo de país.
- [ ] Cargar `telefono_fijo` y `direccion` del almacén en esa misma pantalla
  (son la alternativa visible si el WhatsApp llega a fallar, y la dirección
  alimenta el pie de página y la sección de taller).
- [ ] Entrar al admin y confirmar que **no aparece la franja amarilla de
  avisos** arriba (número mal configurado / inventario sin actualizar).
- [ ] Importar el inventario real de Celeste (ver arriba).

## Despliegue en Railway (igual que TuTaller)
1. Subir este repo a GitHub y crear proyecto en Railway con PostgreSQL
2. Variables (ver `.env.example`): `SECRET_KEY`, `DATABASE_URL` (automática al
   agregar el plugin de Postgres), `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_ORIGIN`
3. `python manage.py createsuperuser` en la consola de Railway

### Fotos subidas desde el admin → volumen persistente (OBLIGATORIO)
El disco del contenedor es **efímero**: sin volumen, toda foto que Ana suba
desde el admin se pierde en el siguiente deploy. Configurar en Railway:
1. En el servicio → **Volumes** → montar un volumen (ej. mount path `/data`).
2. Variable de entorno: `MEDIA_ROOT=/data/media`.

Con eso, `/media/...` se sirve desde el volumen (ver `supermotos_backend/urls.py`;
ya no depende de `DEBUG`). Las **imágenes de categoría** del catálogo NO usan
esto: van en `static/img/` (en git, las sirve WhiteNoise). El volumen es solo
para las fotos por-producto/moto que suba la dueña.

### ⚠️ Las migraciones se corren A MANO (por ahora)
`railway.json` define `preDeployCommand: python manage.py migrate`, pero **hoy
Railway no lo está aplicando** (se descubrió al desplegar: hubo que correr las
migraciones desde la consola). El `Procfile` **solo** levanta gunicorn, no
migra. Hasta que el pre-deploy quede arreglado, después de **cada push que
traiga una migración nueva** hay que entrar a la consola de Railway y correr:

```bash
/opt/venv/bin/python manage.py migrate
```

Migraciones que **no pueden saltarse** (tocan datos, no solo el esquema):
- `0005_poblar_texto_busqueda` — llena `texto_busqueda` de todos los productos
- `0008_migrar_estados_cotizacion` — mapea los estados viejos de cotización
- `0010_reparsear_nombres` — **re-parsea los ~3.088 productos ya cargados** con
  el parser de nombres corregido; sin ella, el catálogo en producción sigue
  mostrando el código dentro del nombre ("VH10384 KIT CILINDRO…")

## Pendientes cuando llegue el Excel real
- [ ] Validar mapeo de columnas con el archivo real de Ana
- [ ] Cargar los 3.062 productos y revisar categorías
- [ ] Definir rutina de actualización con la dueña (diaria/semanal)
- [ ] Fase 2: conectar WhatsApp Cloud API a estos mismos endpoints
