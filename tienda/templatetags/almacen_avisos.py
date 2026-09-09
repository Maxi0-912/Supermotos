"""Avisos operativos que se muestran arriba de TODAS las páginas del admin
(ver tienda/templates/admin/base_site.html). Son cosas que, si nadie las mira,
el sitio sigue funcionando pero mal: número de WhatsApp mal configurado (el
sitio esconde el botón) e inventario sin actualizar hace días. Cada aviso
enlaza directo a la pantalla donde se resuelve."""
from datetime import timedelta

from django import template
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from tienda.models import ConfiguracionSitio, ImportacionInventario

register = template.Library()

# Celeste se exporta a diario; más de esto sin importar es una señal de que
# alguien dejó de subir el Excel y los precios/stock del sitio están viejos.
HORAS_INVENTARIO_VIEJO = 48


def _avisos():
    """Lista de (mensaje, url_para_resolverlo, texto_del_enlace)."""
    avisos = []

    cfg = ConfiguracionSitio.objects.first()
    if cfg is None or not cfg.whatsapp_valido:
        sin_alterno = cfg is None or not (cfg.telefono_fijo or cfg.direccion)
        if sin_alterno:
            # Estado de arranque de cualquier instalación nueva: sin WhatsApp y
            # sin nada que mostrar en su lugar, el cliente no tiene NINGUNA vía
            # de contacto. Se avisan las dos cosas juntas.
            avisos.append((
                "No hay datos de contacto configurados: falta el WhatsApp del "
                "asesor y también el teléfono fijo / la dirección que se muestran "
                "cuando el WhatsApp no está disponible. Ahora mismo el cliente no "
                "tiene forma de contactar al almacén desde el sitio.",
                reverse("admin:tienda_configuracionsitio_changelist"),
                "Completar los datos de contacto",
            ))
        else:
            avisos.append((
                "El WhatsApp del asesor no está configurado o no es válido: el "
                "sitio está ocultando el botón de WhatsApp y mostrando el "
                "teléfono/dirección en su lugar.",
                reverse("admin:tienda_configuracionsitio_changelist"),
                "Configurar el WhatsApp",
            ))

    subir_url = reverse("admin:tienda_importacioninventario_subir")
    ultima = ImportacionInventario.objects.order_by("-fecha").first()
    if ultima is None:
        avisos.append((
            "Todavía no se importó ningún inventario de Celeste: el catálogo del "
            "sitio está vacío o desactualizado.",
            subir_url, "Subir el Excel de Celeste",
        ))
    else:
        atraso = timezone.now() - ultima.fecha
        if atraso > timedelta(hours=HORAS_INVENTARIO_VIEJO):
            horas = int(atraso.total_seconds() // 3600)
            avisos.append((
                format_html(
                    "El inventario no se actualiza hace {} horas (última "
                    "importación: {}).",
                    horas, ultima.fecha.strftime("%d/%m/%Y %H:%M"),
                ),
                subir_url, "Subir el Excel de Celeste",
            ))

    return avisos


@register.simple_tag
def avisos_almacen():
    avisos = _avisos()
    if not avisos:
        return ""
    filas = format_html_join(
        "", '<li class="warning">{} <a href="{}"><b>{} →</b></a></li>',
        ((msg, url, cta) for msg, url, cta in avisos),
    )
    return format_html('<ul class="messagelist">{}</ul>', filas)
