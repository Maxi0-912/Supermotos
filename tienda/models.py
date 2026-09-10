import re
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F

from .busqueda import normalizar


# ==========================================================================
# PARSEO DE DESCRIPCIONES DE CELESTE
# Ejemplo real: "01210-K14-910 KIT CILINDRO (CB 110) DREAN"
#   -> referencia Honda: 01210-K14-910
#   -> nombre: KIT CILINDRO
#   -> modelos: CB110, DREAN
# ==========================================================================

# Formatos de referencia detectados en el inventario real de Celeste:
#   Honda estándar:   17211-KRH-780 / 01210-K1L-D00
#   Con letra final:  20K1110S / 24K150LS / 25K160S
#   Numérica larga:   10110101 / 1011047
#   Con guiones var.: 1-KVC-890 / 02-46-312-72 / 93901-25080
REF_PATRONES = [
    # Honda con sufijo largo y hasta cuarto bloque: 08233-M99-K1LQD, 13011-ABZ-000S-STD
    re.compile(r'^([0-9A-Za-z]{4,6}-[0-9A-Za-z]{2,4}-[0-9A-Za-z]{2,7}(?:-[0-9A-Za-z]{2,4})?)\s'),
    re.compile(r'^(\d{1,3}-[0-9A-Za-z]{2,4}-\d{2,4})\s'),   # 1-KVC-890
    re.compile(r'^(\d{2}-\d{2}-\d{2,3}-\d{2,3})\s'),        # 02-46-312-72
    re.compile(r'^(\d{4,6}-\d{4,6})\s'),                    # 93901-25080
    re.compile(r'^(\d{2,3}[A-Z]\d{2,4}[A-Z]{0,2})\s'),      # 20K1110S / 24K150LS
    re.compile(r'^(\d{6,10})\s'),                           # 10110101 / 825127
]

# Ruido tipo número de lista pegado a la referencia o al nombre: "(781)", "(930)"
RUIDO_INICIO_RE = re.compile(r'^\(\d+\)\s*')
# Cuando el (NNN) quedó pegado a la referencia: "17211-KRH-780(781) FILTRO"
RUIDO_PEGADO_RE = re.compile(r'\(\d{1,4}\)')

# Modelos comunes en Colombia. El almacén vende Honda y también genéricos
# para otras marcas (AKT, Bajaj, Yamaha, etc.), visto en el inventario real.
MODELOS_CONOCIDOS = [
    # Honda
    "CB110", "CB125", "CB125F", "CB160", "CB160F", "CB190", "CB190R", "CB1",
    "CBF125", "CBF150", "CBF160", "XR150", "XR150L", "XR190", "XR190L",
    "XRE190", "XRE300", "XBLADE", "X-BLADE", "INVICTA", "DREAM NEO",
    "DREAN NEO", "DREAM", "DREAN", "DIO", "NAVI", "CD100", "CD 100",
    "POWER SPOR", "TOOL", "BIZ", "WAVE", "ELITE", "C90",
    # Otras marcas frecuentes
    "ECO DELUXE", "ECO", "SPLENDOR", "BOXER", "PLATINO", "AK125", "AK-125",
    "PULSAR", "DISCOVER", "GN125", "BWS", "CRYPTON", "LIBERO", "FZ",
    "NKD", "TTR", "AK", "APACHE", "GIXXER",
]

# --------------------------------------------------------------------------
# EXTENSIONES para los nombres ilegibles vistos con el inventario real
# cargado (3.088 productos). Todo lo de abajo AMPLÍA el parser; REF_PATRONES
# y la lógica de arriba no se tocan.
#
# Patrones de referencia ADICIONALES. Se prueban DESPUÉS de REF_PATRONES, así
# que ninguna descripción que hoy matchea con los de arriba cambia de
# resultado. Cubren formatos del inventario real que hoy caen fuera:
REF_PATRONES_EXT = [
    # sufijo de lote de Celeste pegado con "/": "342123/51", "43082-1128/51"
    re.compile(r'^([0-9A-Za-z]{4,6}(?:-[0-9A-Za-z]{2,7}){0,3})/\d{1,3}(?=\s|$)'),
    # Honda de ferretería, bloque medio de 4-5 díg.: "93892-05012-08", "96001-06016-00S"
    re.compile(r'^(\d{4,6}-\d{4,6}-\d{1,3}[A-Za-z]{0,2})(?=\s|$)'),
    # referencia con un guion pegado al nombre: "50661-KRH-900-CAUCHO", "16111-K38-901-"
    re.compile(r'^([0-9A-Za-z]{4,6}-[0-9A-Za-z]{2,4}-[0-9A-Za-z]{2,7})(?=-)'),
    # numérica con sufijo de color/talla: "818212-AZ-L"
    re.compile(r'^(\d{6}-[A-Za-z]{1,3}(?:-[0-9A-Za-z]{1,3})?)(?=\s|$)'),
]

# Código de proveedor NO Honda al inicio: "VH10384", "NYS06132", "CAB2551",
# "M401784", "NGK7101561", "DD121181", y rodamientos "6004ZZEC3" / "6203ZZ-C3".
# El sufijo tras el bloque de dígitos solo se admite si empieza por letra y
# trae un dígito ("K12913HF100DS") o son <=3 letras seguidas de separador
# ("E32005JS/..."): así "VH20059JUEGO" NO se traga la palabra "JUEGO" -- eso
# lo separa _desglosar_pegado y luego se reintenta la extracción.
COD_PROVEEDOR_RE = re.compile(
    r'^(?:[A-Za-z]{1,4}\d{4,}(?:[A-Za-z][0-9A-Za-z]*\d[0-9A-Za-z]*|[A-Za-z]{1,3})?'
    r'|\d{4}[A-Za-z]{2,}[0-9A-Za-z\-]{0,4})(?=[\s/\-]|$)')

# Referencia (Honda o de proveedor) PEGADA a la primera palabra, sin espacio:
#   "88110-KRH-901ESPEJO"  "16111-K43-D41PISTON"  "VH20059JUEGO"
# Solo se usa como último recurso, si la extracción normal no encontró nada
# (así "52400-KST-951ZAS ...", donde ZAS es sufijo de color, no se parte).
_GLUE_HONDA_RE = re.compile(r'^(\d{3,6}-[0-9A-Z]{1,4}-[0-9A-Z]*\d)([A-Z]{4,})', re.I)
_GLUE_PROV_RE  = re.compile(r'^([A-Z]{1,4}\d{4,}\d*)([A-Z]{3,})', re.I)

# Separadores sueltos + un sufijo corto de lote/revisión que Celeste deja tras
# la referencia: "/51 ", "- ", "-08 ", "00S ", "-0S ".
SUFIJO_REF_RE = re.compile(r'^[\s/\-]+(?:\d{1,3}[A-Za-z]{0,2}(?=\s|$))?[\s/\-]*')

# Referencia Honda genuina que quedó incrustada dentro del nombre (alterna, de
# superseción, entre paréntesis). Se quita SOLO si el nombre conserva palabras
# legibles después.
REF_HONDA_INCRUSTADA_RE = re.compile(
    r'\(?\s*\b\d{4,6}-[0-9A-Za-z]{2,4}-[0-9A-Za-z]{2,7}(?:-[0-9A-Za-z]{1,4})?\b\s*\)?')

# Una "palabra legible" para un cliente: >=4 letras seguidas.
_PALABRA_LEGIBLE_RE = re.compile(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}')
# Referencia / código que NUNCA debería quedar dentro del nombre.
_CODIGO_EN_NOMBRE_RE = re.compile(
    r'\d{3,6}-[0-9A-Za-z]{2,4}-[0-9A-Za-z]{2,7}|^[A-Za-z]{1,4}\d{4,}')


def _desglosar_pegado(t):
    t = _GLUE_HONDA_RE.sub(r'\1 \2', t, count=1)
    t = _GLUE_PROV_RE.sub(r'\1 \2', t, count=1)
    return t


def _quitar_ref_inicial(texto, con_proveedor=False):
    """(referencia_o_'', resto) quitando UNA referencia del inicio de `texto`.
    Prueba primero extracción limpia (patrón + frontera). Solo si nada matchea
    y el token inicial parece una referencia pegada a una palabra, la separa y
    reintenta."""
    def _match(t):
        for patron in REF_PATRONES + REF_PATRONES_EXT:
            m = patron.match(t + " ")  # el espacio ayuda al \s / (?=\s) final
            if m:
                return m.group(1).upper(), t[m.end(1):]
        if con_proveedor:
            m = COD_PROVEEDOR_RE.match(t)
            if m:
                return m.group(0).upper().strip(), t[m.end():]
        return None

    r = _match(texto)
    if r:
        return r
    separado = _desglosar_pegado(texto)
    if separado != texto:
        r = _match(separado)
        if r:
            return r
    return "", texto


def parsear_descripcion(descripcion: str) -> dict:
    """Extrae referencia Honda, nombre limpio y modelos compatibles
    de una descripción de producto tal como viene de Celeste."""
    texto = (descripcion or "").strip()
    # Quitar números de lista "(781)" que Celeste pega dentro de la descripción
    texto = RUIDO_PEGADO_RE.sub(" ", texto)
    texto = re.sub(r'\s{2,}', ' ', texto).strip()

    referencia, texto = _quitar_ref_inicial(texto, con_proveedor=True)
    texto = SUFIJO_REF_RE.sub("", texto.strip(), count=1)

    # Segunda / tercera referencia pegada al inicio: Celeste a veces encadena
    # la referencia vieja y la nueva ("16111-K38-901- 16111-K43-D41PISTON...").
    for _ in range(2):
        ref2, resto = _quitar_ref_inicial(texto.strip(), con_proveedor=True)
        if not ref2:
            break
        texto = SUFIJO_REF_RE.sub("", resto.strip(), count=1)

    # Quitar ruido tipo "(781) " que a veces queda al inicio del nombre
    texto = RUIDO_INICIO_RE.sub("", texto.strip()).strip()

    # Referencia Honda incrustada más adentro del nombre (alterna / entre
    # paréntesis). Solo se toca el nombre si de verdad hay una referencia que
    # quitar y si al quitarla el nombre conserva palabras legibles.
    if REF_HONDA_INCRUSTADA_RE.search(texto):
        limpio = REF_HONDA_INCRUSTADA_RE.sub(" ", texto)
        limpio = re.sub(r'\(\s*\)', ' ', limpio)
        limpio = re.sub(r'\s{2,}', ' ', limpio).strip(" -/")
        if limpio and re.search(r'[A-Za-zÑñ]{3,}', limpio):
            texto = limpio

    # Solo separadores sueltos que dejó el recorte de la referencia (no se toca
    # la puntuación interna del nombre original: "IZQ.", "CBF150/").
    texto = texto.lstrip(" -/").strip()

    # Detectar modelos mencionados (con o sin espacios: "CB 160F" == "CB160F")
    texto_normalizado = re.sub(r'\s+', '', texto.upper()).replace('-', '')
    modelos = []
    for modelo in sorted(MODELOS_CONOCIDOS, key=len, reverse=True):
        clave = modelo.replace(' ', '').replace('-', '')
        if clave in texto_normalizado:
            ya = [x.replace(' ', '').replace('-', '') for x in modelos]
            if not any(clave in y or y in clave for y in ya):
                modelos.append(modelo)

    nombre = texto.strip()
    # Si se extrajo una referencia y no quedó nada más, el nombre queda vacío
    # a propósito (la descripción de Celeste era solo un código): el fallback
    # de tarjeta y el filtro del admin lo recogen. Solo se cae a `descripcion`
    # cuando NO hubo referencia que extraer.
    if not nombre and not referencia:
        nombre = descripcion
    return {
        "referencia": referencia,
        "nombre": nombre,
        "modelos": modelos,
    }


def nombre_es_ilegible(nombre: str) -> bool:
    """True si el nombre no le dice nada a un cliente: vacío, puro código, o
    con una referencia todavía incrustada. Lo usa el filtro del admin para que
    Ana encuentre los productos por arreglar a mano."""
    n = (nombre or "").strip()
    if len(n) < 4:
        return True
    if not _PALABRA_LEGIBLE_RE.search(n):
        return True
    if _CODIGO_EN_NOMBRE_RE.search(n):
        return True
    return False


class Producto(models.Model):
    """Producto sincronizado desde Celeste MIPYME.
    La llave de sincronización es codigo_celeste (columna Código del export)."""
    codigo_celeste = models.CharField("Código Celeste", max_length=30, unique=True)
    referencia = models.CharField("Referencia Honda", max_length=40, blank=True, db_index=True)
    nombre = models.CharField("Nombre", max_length=250)
    descripcion_original = models.CharField("Descripción original (Celeste)", max_length=300, blank=True)
    categoria = models.CharField("Categoría", max_length=100, blank=True, db_index=True)
    marca = models.CharField("Marca", max_length=60, default="Honda")
    precio = models.DecimalField("Precio público", max_digits=12, decimal_places=0, default=0)
    stock = models.IntegerField("Stock disponible", default=0)
    modelos_compatibles = models.CharField(
        "Modelos compatibles", max_length=250, blank=True,
        help_text="Separados por coma. Se llena automático al importar; se puede corregir a mano.")
    imagen = models.ImageField("Foto del producto", upload_to="productos/", blank=True, null=True)
    imagen_url = models.URLField("Foto por URL", blank=True,
        help_text="Pega el enlace de una imagen si no quieres subir archivo")
    activo = models.BooleanField("Visible en la web", default=True)
    actualizado = models.DateTimeField(auto_now=True)
    # Sin db_index: un B-tree normal no acelera un icontains ("LIKE '%x%'",
    # comodín al inicio) -- confirmado con EXPLAIN QUERY PLAN en SQLite, sale
    # "SCAN tienda_producto" con o sin índice. Además se recalcula en los
    # ~3.088 productos en cada importación completa, así que un índice acá
    # solo sumaría costo de escritura sin beneficio de lectura.
    # Si la búsqueda se vuelve un cuello de botella real en producción
    # (Postgres vía DATABASE_URL, no SQLite -- FTS5 no aplica, es exclusivo
    # de SQLite): la extensión pg_trgm + un índice GIN sobre esta columna sí
    # acelera icontains, y se agrega en una migración corta (CREATE EXTENSION
    # pg_trgm; índice GIN con gin_trgm_ops) sin tocar este modelo ni
    # busqueda.py. Los 19-22ms medidos para "aceite"/"filtro"/"llanta" son de
    # SQLite local (dev) -- hay que volver a medir contra Postgres en Railway
    # antes de decidir si hace falta pg_trgm.
    texto_busqueda = models.TextField(
        "Texto de búsqueda (uso interno)", blank=True, editable=False,
        help_text="Se recalcula solo en save(); no editar a mano.")

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["nombre"]

    def __str__(self):
        return f"[{self.codigo_celeste}] {self.nombre}"

    @property
    def stock_web(self):
        """Nunca mostrar stock negativo en la página/bot."""
        return max(self.stock, 0)

    @property
    def foto(self):
        """Foto elegida a mano por Ana desde el admin. Nunca se asigna sola:
        si no hay imagen ni URL, el frontend muestra una placa de producto."""
        if self.imagen:
            return self.imagen.url
        if self.imagen_url:
            return self.imagen_url
        return ""

    @property
    def nombre_publico(self):
        """Lo que se muestra en la tarjeta. Si el nombre parseado no le dice
        nada a un cliente (descripción de Celeste que era solo un código), se
        arma un rótulo con lo que sí se tiene -- marca, referencia y modelos
        compatibles -- en vez de dejar la tarjeta con un código o vacía. No se
        inventa una descripción: solo se reordena lo que ya está en la ficha.
        Estos productos igual salen en el filtro 'Nombre legible = No' del
        admin para que Ana les ponga un nombre de verdad."""
        if not nombre_es_ilegible(self.nombre):
            return self.nombre
        modelos = self.modelos_compatibles.strip()
        ref = (self.referencia or self.codigo_celeste or "").strip()
        base = f"Repuesto {self.marca}".strip() if self.marca else "Repuesto"
        if ref:
            base = f"{base} · ref. {ref}"
        if modelos:
            base = f"{base} — para {modelos}"
        return base

    def save(self, *args, **kwargs):
        # texto_busqueda se recalcula SIEMPRE al guardar (el importador usa
        # update_or_create, que llama a save() tanto al crear como al
        # actualizar) para que nunca quede desactualizado si el producto
        # cambia de nombre o de modelos compatibles.
        self.texto_busqueda = normalizar(
            f"{self.referencia} {self.nombre} {self.modelos_compatibles} {self.categoria}")
        # update_or_create() (el que usa el importador) llama a save() con
        # update_fields=<solo los campos que cambiaron>. Sin este ajuste, el
        # UPDATE de SQL nunca incluiría texto_busqueda -- quedaría recalculado
        # en el objeto en memoria pero NO escrito en la base de datos.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"texto_busqueda"}
        super().save(*args, **kwargs)


class Cotizacion(models.Model):
    # nueva -> tomada -> vendida
    #               \-> perdida (motivo obligatorio, ver clean())
    # Dos vendedores comparten un solo WhatsApp: "tomada" (+ asesor/tomada_en)
    # es lo que evita que los dos trabajen la misma cotización sin saberlo.
    ESTADOS = [
        ("nueva", "Nueva"),
        ("tomada", "Tomada"),
        ("vendida", "Vendida"),
        ("perdida", "Perdida"),
    ]
    MOTIVOS_PERDIDA = [
        ("sin_stock", "Sin stock real"),
        ("precio", "Precio"),
        ("no_contesto", "No contestó"),
        ("otro_lado", "Compró en otro lado"),
        ("otro", "Otro"),
    ]
    nombre_cliente = models.CharField("Nombre del cliente", max_length=120, blank=True)
    telefono = models.CharField("Teléfono / WhatsApp", max_length=30, blank=True)
    estado = models.CharField(max_length=15, choices=ESTADOS, default="nueva")
    origen = models.CharField(max_length=20, default="web")  # web | web-agotado | moto
    # Texto libre y no FK a User: son dos vendedores de mostrador compartiendo
    # un WhatsApp, sin cuentas propias en el panel. Si el equipo crece y hace
    # falta forzar login por vendedor, esto se migra a FK sin perder datos.
    asesor = models.CharField("Asesor que la tomó", max_length=80, blank=True)
    tomada_en = models.DateTimeField("Tomada el", null=True, blank=True)
    motivo_perdida = models.CharField("Motivo de pérdida", max_length=20,
        choices=MOTIVOS_PERDIDA, blank=True)
    notas_asesor = models.TextField("Notas del asesor", blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cotización"
        verbose_name_plural = "Cotizaciones"
        ordering = ["-creada"]

    def __str__(self):
        return f"Cotización #{self.id:04d} ({self.get_estado_display()})"

    def clean(self):
        if self.estado == "perdida":
            if not self.motivo_perdida:
                raise ValidationError(
                    {"motivo_perdida": "Obligatorio al marcar la cotización como perdida."})
        else:
            # motivo_perdida solo significa algo si estado == "perdida". Si un
            # vendedor saca la cotización de ese estado (los dos comparten el
            # WhatsApp y se corrigen entre sí), se limpia el motivo: una
            # cotización vendida con motivo "no contestó" contaminaría el dato
            # de pérdidas, que es el más valioso a mediano plazo. Con esto
            # marcar_vendida / marcar_tomada lo limpian sin código extra.
            self.motivo_perdida = ""

    def save(self, *args, **kwargs):
        # full_clean() (no solo la validación del form del admin) para que la
        # regla de motivo_perdida obligatorio se cumpla también desde una
        # acción masiva o desde el shell, no únicamente al editar a mano.
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum(i.subtotal for i in self.items.all())


class ItemCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=0)

    class Meta:
        verbose_name = "Ítem de cotización"
        verbose_name_plural = "Ítems de cotización"

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario


class Cita(models.Model):
    SERVICIOS = [
        ("mantenimiento", "Mantenimiento general"),
        ("aceite", "Cambio de aceite y filtro"),
        ("frenos", "Revisión de frenos"),
        ("inyeccion", "Diagnóstico de inyección"),
        ("otro", "Otro"),
    ]
    ESTADOS = [
        ("pendiente", "Pendiente por confirmar"),
        ("confirmada", "Confirmada"),
        ("atendida", "Atendida"),
        ("cancelada", "Cancelada"),
    ]
    nombre_cliente = models.CharField("Nombre del cliente", max_length=120)
    telefono = models.CharField("Teléfono / WhatsApp", max_length=30)
    servicio = models.CharField(max_length=20, choices=SERVICIOS, default="mantenimiento")
    moto = models.CharField("Moto (modelo/placa)", max_length=100, blank=True)
    fecha = models.DateField("Fecha")
    hora = models.TimeField("Hora")
    estado = models.CharField(max_length=15, choices=ESTADOS, default="pendiente")
    notas = models.TextField(blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cita de taller"
        verbose_name_plural = "Citas de taller"
        ordering = ["fecha", "hora"]

    def __str__(self):
        return f"{self.nombre_cliente} — {self.get_servicio_display()} {self.fecha} {self.hora}"


class VentaRapida(models.Model):
    """Registro opcional de ventas en mostrador para descontar stock
    entre importaciones de Celeste."""
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="ventas")
    cantidad = models.PositiveIntegerField(default=1)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Venta rápida (mostrador)"
        verbose_name_plural = "Ventas rápidas (mostrador)"
        ordering = ["-fecha"]

    def save(self, *args, **kwargs):
        es_nueva = self.pk is None
        super().save(*args, **kwargs)
        if es_nueva:
            # Descuento atómico: nunca deja stock negativo por concurrencia
            Producto.objects.filter(pk=self.producto_id, stock__gte=self.cantidad) \
                .update(stock=F("stock") - self.cantidad)


class ImportacionInventario(models.Model):
    """Historial de cargas del Excel exportado de Celeste."""
    archivo = models.FileField(upload_to="importaciones/")
    fecha = models.DateTimeField(auto_now_add=True)
    creados = models.PositiveIntegerField(default=0)
    actualizados = models.PositiveIntegerField(default=0)
    errores = models.TextField(blank=True)

    class Meta:
        verbose_name = "Importación de inventario"
        verbose_name_plural = "Importaciones de inventario"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Importación {self.fecha:%d/%m/%Y %H:%M} (+{self.creados} nuevos, {self.actualizados} actualizados)"


class Motocicleta(models.Model):
    """Motos Honda NUEVAS del concesionario (catálogo separado de los
    repuestos usados/genéricos que vienen de Celeste)."""
    nombre = models.CharField("Modelo", max_length=120)              # ej: CB 160F DLX
    marca = models.CharField(max_length=60, default="Honda")
    precio = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    cilindraje = models.CharField(max_length=30, blank=True)          # ej: 162 cc
    categoria = models.CharField(max_length=40, blank=True,           # naked, enduro, scooter, trabajo
        help_text="naked, enduro, scooter, semiautomática, etc.")
    descripcion = models.TextField(blank=True)
    imagen = models.ImageField("Foto principal", upload_to="motos/", blank=True, null=True)
    imagen_url = models.URLField("Foto por URL", blank=True)
    destacada = models.BooleanField("Mostrar como destacada", default=False)
    disponible = models.BooleanField("Disponible", default=True)
    orden = models.PositiveIntegerField(default=100, help_text="Menor número aparece primero")

    class Meta:
        verbose_name = "Motocicleta"
        verbose_name_plural = "Motocicletas"
        ordering = ["orden", "precio"]

    def __str__(self): return f"{self.marca} {self.nombre}"

    @property
    def foto(self):
        if self.imagen: return self.imagen.url
        if self.imagen_url: return self.imagen_url
        return ""


class ConfiguracionSitio(models.Model):
    """Configuración general del sitio (singleton: una sola fila).
    Fuente ÚNICA de los datos de contacto en todo el proyecto (bot, pie de
    página, sección de taller): así no quedan quemados en el HTML ni repetidos
    en tres formatos distintos, y Ana los cambia desde el admin."""
    # Sin default: en instalación nueva queda vacío y el frontend degrada al
    # teléfono/dirección en vez de generar un wa.me con un número inventado.
    # El viejo default "57" era una trampa: producía un enlace válido en forma
    # pero inútil en destino, sin que nada avisara.
    whatsapp_asesor = models.CharField("WhatsApp del asesor", max_length=20, blank=True,
        help_text="Solo dígitos, con indicativo de país: 10 a 15. Ej: 573001234567. "
                  "Si queda vacío o mal, el sitio oculta el botón de WhatsApp y "
                  "muestra el teléfono fijo / la dirección en su lugar.")
    nombre_asesor = models.CharField(max_length=80, blank=True, default="Asesor comercial")
    telefono_fijo = models.CharField("Teléfono fijo del almacén", max_length=30, blank=True,
        help_text="Alternativa visible cuando el WhatsApp no está disponible. Opcional.")
    direccion = models.CharField("Dirección del almacén", max_length=200, blank=True,
        help_text="Se usa en el pie de página, la sección de taller y como "
                  "alternativa al WhatsApp. Opcional.")

    class Meta:
        verbose_name = "Configuración del sitio"
        verbose_name_plural = "Configuración del sitio"

    def __str__(self): return "Configuración del sitio"

    def clean(self):
        # Normaliza a solo dígitos y valida un largo plausible (rango E.164,
        # 10-15). Vacío se permite (el frontend degrada). Un número presente
        # pero corto -- "57", "300123" -- se rechaza con un mensaje para Ana
        # en vez de romper en silencio todos los botones de WhatsApp del sitio.
        self.whatsapp_asesor = re.sub(r"\D", "", self.whatsapp_asesor or "")
        if self.whatsapp_asesor and not (10 <= len(self.whatsapp_asesor) <= 15):
            raise ValidationError({"whatsapp_asesor":
                "El WhatsApp debe tener entre 10 y 15 dígitos e incluir el indicativo "
                "de país (Colombia: 57). Ejemplo: 573001234567."})

    @property
    def whatsapp_valido(self):
        """Mismo criterio que usa el frontend para decidir si muestra el botón."""
        return 10 <= len(self.whatsapp_asesor or "") <= 15
