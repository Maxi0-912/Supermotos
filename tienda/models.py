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


def parsear_descripcion(descripcion: str) -> dict:
    """Extrae referencia Honda, nombre limpio y modelos compatibles
    de una descripción de producto tal como viene de Celeste."""
    texto = (descripcion or "").strip()
    # Quitar números de lista "(781)" que Celeste pega dentro de la descripción
    texto = RUIDO_PEGADO_RE.sub(" ", texto)
    texto = re.sub(r'\s{2,}', ' ', texto).strip()
    referencia = ""

    for patron in REF_PATRONES:
        m = patron.match(texto + " ")  # el espacio ayuda al \s final
        if m:
            referencia = m.group(1).upper()
            texto = texto[len(m.group(1)):].strip()
            break

    # Quitar ruido tipo "(781) " que a veces queda al inicio del nombre
    texto = RUIDO_INICIO_RE.sub("", texto).strip()

    # Detectar modelos mencionados (con o sin espacios: "CB 160F" == "CB160F")
    texto_normalizado = re.sub(r'\s+', '', texto.upper()).replace('-', '')
    modelos = []
    for modelo in sorted(MODELOS_CONOCIDOS, key=len, reverse=True):
        clave = modelo.replace(' ', '').replace('-', '')
        if clave in texto_normalizado:
            ya = [x.replace(' ', '').replace('-', '') for x in modelos]
            if not any(clave in y or y in clave for y in ya):
                modelos.append(modelo)

    return {
        "referencia": referencia,
        "nombre": texto or descripcion,
        "modelos": modelos,
    }


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
    Así el número de WhatsApp del asesor no queda quemado en el código
    y Ana lo puede cambiar desde el admin."""
    whatsapp_asesor = models.CharField("WhatsApp del asesor", max_length=20,
        default="57", help_text="Solo números con indicativo, ej: 573001234567")
    nombre_asesor = models.CharField(max_length=80, blank=True, default="Asesor comercial")

    class Meta:
        verbose_name = "Configuración del sitio"
        verbose_name_plural = "Configuración del sitio"

    def __str__(self): return "Configuración del sitio"
