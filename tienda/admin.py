from urllib.parse import quote_plus

from django.contrib import admin
from django import forms
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.shortcuts import redirect
from django.urls import path
from django.template.response import TemplateResponse
from django.contrib import messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (Producto, Cotizacion, ItemCotizacion,
                     VentaRapida, ImportacionInventario,
                     Motocicleta, ConfiguracionSitio, nombre_es_ilegible)
from .importador import importar_excel

admin.site.site_header = "SuperMotos La 4ta — Panel de administración"
admin.site.site_title = "SuperMotos La 4ta"
admin.site.index_title = "Gestión del almacén"


class ConFotoFilter(admin.SimpleListFilter):
    """Para ir completando fotos de a poco: filtra los productos/motos que
    ya tienen foto elegida por Ana de los que todavía no. Sirve para
    cualquier modelo con campos `imagen` (ImageField) e `imagen_url`."""
    title = "foto"
    parameter_name = "con_foto"

    def lookups(self, request, model_admin):
        return [("si", "Con foto"), ("no", "Sin foto")]

    def queryset(self, request, queryset):
        # Las filas que ya existían antes de agregar el campo quedaron con
        # imagen=NULL (no ""), así que hay que contemplar ambos casos.
        sin_imagen = (Q(imagen="") | Q(imagen__isnull=True)) & Q(imagen_url="")
        if self.value() == "si":
            return queryset.exclude(sin_imagen)
        if self.value() == "no":
            return queryset.filter(sin_imagen)
        return queryset


class NombreLegibleFilter(admin.SimpleListFilter):
    """Cola de trabajo para Ana: los productos cuyo nombre no le dice nada a un
    cliente (la descripción de Celeste era solo un código, o quedó una
    referencia incrustada). Se filtran para irlos corrigiendo a mano en el
    campo «Nombre»."""
    title = "nombre legible"
    parameter_name = "nombre_legible"

    def lookups(self, request, model_admin):
        return [("no", "No — por revisar"), ("si", "Sí")]

    def queryset(self, request, queryset):
        valor = self.value()
        if valor not in ("si", "no"):
            return queryset
        # Se evalúa en Python (el criterio es una heurística de texto, no una
        # condición SQL). Son ~3 mil filas y una cadena corta por fila: barato
        # para una pantalla de administración.
        ilegibles = [pk for pk, nombre in queryset.values_list("pk", "nombre")
                     if nombre_es_ilegible(nombre)]
        if valor == "no":
            return queryset.filter(pk__in=ilegibles)
        return queryset.exclude(pk__in=ilegibles)


class BuscadorFotoAdminMixin:
    """Miniatura en el listado + vista previa grande y botón 'Buscar en
    Google Imágenes' con el nombre del objeto ya puesto, en el detalle.
    Ana elige la imagen que reconoce y pega el enlace en 'Foto por URL'
    (o la descarga y la sube en 'Foto del producto'/'Foto principal').
    El sistema nunca asigna una foto solo. Reutilizado por Producto y
    Motocicleta, que comparten los campos `imagen`/`imagen_url`/`foto`."""

    def miniatura(self, obj):
        if obj.foto:
            return format_html(
                '<img src="{}" style="width:44px;height:44px;object-fit:cover;'
                'border-radius:6px;border:1px solid #ddd">', obj.foto)
        return mark_safe('<span style="color:#999;font-size:12px">Sin foto</span>')
    miniatura.short_description = "Foto"

    def vista_previa(self, obj):
        partes = []
        if obj.foto:
            partes.append(format_html(
                '<img src="{}" style="max-width:220px;max-height:220px;object-fit:contain;'
                'border:1px solid #ddd;border-radius:8px;padding:4px;background:#fafafa"><br><br>',
                obj.foto))
        else:
            partes.append(mark_safe(
                '<div style="color:#888;padding:6px 0;max-width:340px;line-height:1.5">'
                'Sin foto todavía. Busca en Google, elige la imagen correcta, y pega su '
                'enlace en «Foto por URL» — o descárgala y súbela en el campo de archivo.</div>'))
        if obj and obj.pk and obj.nombre:
            url_busqueda = "https://www.google.com/search?tbm=isch&q=" + quote_plus(obj.nombre)
            partes.append(format_html(
                '<a href="{}" target="_blank" rel="noopener" '
                'style="display:inline-block;margin-top:6px;padding:8px 16px;background:#1a73e8;'
                'color:#fff;border-radius:5px;text-decoration:none;font-weight:600">'
                '🔍 Buscar imágenes en Google</a>', url_busqueda))
        return mark_safe("".join(partes))
    vista_previa.short_description = "Vista previa / buscar foto"


@admin.register(Producto)
class ProductoAdmin(BuscadorFotoAdminMixin, admin.ModelAdmin):
    list_display = ["miniatura", "codigo_celeste", "referencia", "nombre_col", "categoria",
                    "marca", "precio", "stock", "activo"]
    list_filter = ["activo", NombreLegibleFilter, ConFotoFilter, "marca", "categoria"]
    search_fields = ["codigo_celeste", "referencia", "nombre", "modelos_compatibles"]
    list_editable = ["precio", "stock", "activo"]
    list_per_page = 50
    readonly_fields = ["vista_previa"]
    fields = ["codigo_celeste", "referencia", "nombre", "descripcion_original",
              "categoria", "marca", "precio", "stock", "modelos_compatibles",
              "imagen", "imagen_url", "vista_previa", "activo"]

    @admin.display(description="Nombre", ordering="nombre")
    def nombre_col(self, obj):
        """Marca con ⚠ los nombres por revisar y, debajo, muestra lo que hoy
        vería el cliente en la tarjeta (nombre_publico)."""
        if not nombre_es_ilegible(obj.nombre):
            return obj.nombre
        return format_html(
            '<span title="Nombre no legible — por corregir a mano">⚠</span> '
            '<span style="color:#b8860b">{}</span><br>'
            '<small style="color:#888">tarjeta: {}</small>',
            obj.nombre or "(vacío)", obj.nombre_publico)


@admin.register(Motocicleta)
class MotocicletaAdmin(BuscadorFotoAdminMixin, admin.ModelAdmin):
    list_display = ["miniatura", "nombre", "marca", "precio", "categoria",
                    "destacada", "disponible", "orden"]
    list_filter = ["disponible", "destacada", ConFotoFilter, "categoria"]
    search_fields = ["nombre", "marca"]
    list_editable = ["precio", "destacada", "disponible", "orden"]
    list_per_page = 50
    readonly_fields = ["vista_previa"]
    fields = ["nombre", "marca", "precio", "cilindraje", "categoria", "descripcion",
              "imagen", "imagen_url", "vista_previa", "destacada", "disponible", "orden"]


@admin.register(ConfiguracionSitio)
class ConfiguracionSitioAdmin(admin.ModelAdmin):
    """Una sola fila: el número de WhatsApp del asesor y su nombre, para
    que Ana los cambie sin tocar código ni pedirle nada a un programador."""
    list_display = ["whatsapp_asesor", "nombre_asesor"]

    def has_add_permission(self, request):
        return not ConfiguracionSitio.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class ItemInline(admin.TabularInline):
    model = ItemCotizacion
    extra = 0


class TomarForm(forms.Form):
    asesor = forms.CharField(label="¿Quién la toma?", max_length=80)


class PerderForm(forms.Form):
    motivo_perdida = forms.ChoiceField(label="Motivo de la pérdida", choices=Cotizacion.MOTIVOS_PERDIDA)


# nueva primero (lo que falta por tomar), después tomada (en curso), y al
# final vendida/perdida (ya resueltas) -- explícito en vez de dejarlo al
# orden alfabético de las claves, que cambiaría si algún día se agrega un
# estado nuevo.
PRIORIDAD_ESTADO = {"nueva": 0, "tomada": 1, "vendida": 2, "perdida": 3}
COLOR_ESTADO = {"nueva": "#c0392b", "tomada": "#b8860b", "vendida": "#0a7d43", "perdida": "#6b7078"}


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ["id", "estado_coloreado", "nombre_cliente", "telefono", "origen",
                     "asesor", "monto_total", "num_items", "creada"]
    list_filter = ["estado", "asesor", "origen"]
    search_fields = ["nombre_cliente", "telefono"]
    inlines = [ItemInline]
    actions = ["marcar_tomada", "marcar_vendida", "marcar_perdida"]

    def get_queryset(self, request):
        # Una sola consulta con todo lo que necesita la lista -- nada de
        # abrir Cotizacion.total (que hace una query por fila) desde acá.
        prioridad = Case(
            *[When(estado=k, then=Value(v)) for k, v in PRIORIDAD_ESTADO.items()],
            default=Value(99), output_field=IntegerField(),
        )
        return super().get_queryset(request).annotate(
            prioridad_estado=prioridad,
            monto_total=Sum(F("items__cantidad") * F("items__precio_unitario")),
            num_items=Count("items"),
        ).order_by("prioridad_estado", "-creada")

    @admin.display(description="Estado", ordering="prioridad_estado")
    def estado_coloreado(self, obj):
        color = COLOR_ESTADO.get(obj.estado, "#333")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_estado_display())

    @admin.display(description="Total", ordering="monto_total")
    def monto_total(self, obj):
        return obj.monto_total or 0

    @admin.display(description="Ítems", ordering="num_items")
    def num_items(self, obj):
        return obj.num_items

    @admin.action(description="Marcar como tomada")
    def marcar_tomada(self, request, queryset):
        return self._accion_con_form(
            request, queryset, TomarForm, "admin/cotizacion_marcar.html",
            titulo="Marcar como tomada",
            aplicar=lambda datos: {"estado": "tomada", "asesor": datos["asesor"],
                                    "tomada_en": timezone.now()},
        )

    @admin.action(description="Marcar como vendida")
    def marcar_vendida(self, request, queryset):
        n = 0
        for c in queryset:
            c.estado = "vendida"
            c.save()
            n += 1
        self.message_user(request, f"{n} cotización(es) marcadas como vendidas.")

    @admin.action(description="Marcar como perdida (pide motivo)")
    def marcar_perdida(self, request, queryset):
        return self._accion_con_form(
            request, queryset, PerderForm, "admin/cotizacion_marcar.html",
            titulo="Marcar como perdida",
            aplicar=lambda datos: {"estado": "perdida", "motivo_perdida": datos["motivo_perdida"]},
        )

    def _accion_con_form(self, request, queryset, form_class, template, titulo, aplicar):
        """Patrón de doble paso (igual al 'eliminar seleccionados' de Django):
        1er POST -> muestra el formulario pidiendo el dato que falta.
        2do POST (con 'aplicar' en el body) -> lo valida y recién ahí actualiza.
        Así motivo_perdida (o el asesor) nunca queda vacío por una acción
        masiva -- el modelo también lo exige en save(), esto es además una
        mejor experiencia que dejar que falle."""
        if "aplicar" in request.POST:
            form = form_class(request.POST)
            if form.is_valid():
                cambios = aplicar(form.cleaned_data)
                n = 0
                for c in queryset:
                    for campo, valor in cambios.items():
                        setattr(c, campo, valor)
                    c.save()
                    n += 1
                self.message_user(request, f"{n} cotización(es) actualizadas.")
                return None
        else:
            form = form_class()
        return TemplateResponse(request, template, {
            **self.admin_site.each_context(request),
            "cotizaciones": queryset,
            "form": form,
            "titulo": titulo,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "action_name": request.POST.get("action", ""),
            "opts": self.model._meta,
        })


@admin.register(VentaRapida)
class VentaRapidaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "producto", "cantidad"]
    autocomplete_fields = ["producto"]


class SubidaForm(forms.Form):
    archivo = forms.FileField(label="Archivo Excel exportado de Celeste")


@admin.register(ImportacionInventario)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "creados", "actualizados"]
    readonly_fields = ["fecha", "creados", "actualizados", "errores"]

    def get_urls(self):
        return [path("subir/", self.admin_site.admin_view(self.subir),
                     name="tienda_importacioninventario_subir")] + super().get_urls()

    def subir(self, request):
        """Pantalla simple: la dueña sube el Excel y listo."""
        if request.method == "POST":
            form = SubidaForm(request.POST, request.FILES)
            if form.is_valid():
                reg = ImportacionInventario.objects.create(archivo=form.cleaned_data["archivo"])
                try:
                    r = importar_excel(reg.archivo.path)
                finally:
                    # No se conserva el Excel: lleva costos y márgenes del
                    # negocio y ya cumplió su función al importarse.
                    reg.archivo.delete(save=False)
                    reg.archivo = ""
                reg.creados, reg.actualizados = r.get("creados", 0), r.get("actualizados", 0)
                reg.errores = "\n".join(r.get("detalles", [])) or r.get("error", "")
                reg.save()
                if r.get("ok"):
                    resumen = (f"Inventario actualizado: {r['creados']} productos nuevos, "
                               f"{r['actualizados']} actualizados, {r['omitidos']} filas omitidas.")
                    if r.get("no_producto"):
                        resumen += (f" {r['no_producto']} fila(s) no son repuesto "
                                    f"(IVA, fletes, servicios): quedaron inactivas.")
                    messages.success(request, resumen)
                else:
                    messages.error(request, r.get("error", "Error desconocido."))
                return redirect("..")
        else:
            form = SubidaForm()
        ctx = dict(self.admin_site.each_context(request), form=form,
                   title="Actualizar inventario desde Celeste")
        return TemplateResponse(request, "admin/subir_inventario.html", ctx)
