from urllib.parse import quote_plus

from django.contrib import admin
from django import forms
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import path
from django.template.response import TemplateResponse
from django.contrib import messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (Producto, Cotizacion, ItemCotizacion, Cita,
                     VentaRapida, ImportacionInventario,
                     Motocicleta, ConfiguracionSitio)
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
    list_display = ["miniatura", "codigo_celeste", "referencia", "nombre", "categoria",
                    "marca", "precio", "stock", "activo"]
    list_filter = ["activo", ConFotoFilter, "marca", "categoria"]
    search_fields = ["codigo_celeste", "referencia", "nombre", "modelos_compatibles"]
    list_editable = ["precio", "stock", "activo"]
    list_per_page = 50
    readonly_fields = ["vista_previa"]
    fields = ["codigo_celeste", "referencia", "nombre", "descripcion_original",
              "categoria", "marca", "precio", "stock", "modelos_compatibles",
              "imagen", "imagen_url", "vista_previa", "activo"]


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


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ["id", "nombre_cliente", "telefono", "origen", "estado", "total", "creada"]
    list_filter = ["estado", "origen"]
    list_editable = ["estado"]
    inlines = [ItemInline]


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "hora", "nombre_cliente", "telefono", "servicio", "moto", "estado"]
    list_filter = ["estado", "servicio", "fecha"]
    list_editable = ["estado"]
    search_fields = ["nombre_cliente", "telefono"]


@admin.register(VentaRapida)
class VentaRapidaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "producto", "cantidad"]
    autocomplete_fields = ["producto"]


class SubidaForm(forms.Form):
    archivo = forms.FileField(label="Archivo Excel exportado de Celeste")


@admin.register(ImportacionInventario)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "creados", "actualizados"]
    readonly_fields = ["fecha", "creados", "actualizados", "errores", "archivo"]

    def get_urls(self):
        return [path("subir/", self.admin_site.admin_view(self.subir),
                     name="tienda_importacioninventario_subir")] + super().get_urls()

    def subir(self, request):
        """Pantalla simple: la dueña sube el Excel y listo."""
        if request.method == "POST":
            form = SubidaForm(request.POST, request.FILES)
            if form.is_valid():
                reg = ImportacionInventario.objects.create(archivo=form.cleaned_data["archivo"])
                r = importar_excel(reg.archivo.path)
                reg.creados, reg.actualizados = r.get("creados", 0), r.get("actualizados", 0)
                reg.errores = "\n".join(r.get("detalles", [])) or r.get("error", "")
                reg.save()
                if r.get("ok"):
                    messages.success(request,
                        f"Inventario actualizado: {r['creados']} productos nuevos, "
                        f"{r['actualizados']} actualizados, {r['omitidos']} filas omitidas.")
                else:
                    messages.error(request, r.get("error", "Error desconocido."))
                return redirect("..")
        else:
            form = SubidaForm()
        ctx = dict(self.admin_site.each_context(request), form=form,
                   title="Actualizar inventario desde Celeste")
        return TemplateResponse(request, "admin/subir_inventario.html", ctx)
