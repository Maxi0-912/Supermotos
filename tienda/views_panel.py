"""Panel interno de cotizaciones: cola del vendedor + resumen de la dueña.

Interfaz propia (no el admin de Django) pensada para mostrador con celular:
móvil primero, cero campos de texto libre en el flujo normal, todo con
botones. Reutiliza el login de Django (auth) tal cual -- no hay usuarios,
permisos ni sesiones nuevas. "Vendedor" = cualquier usuario con is_staff;
"dueña" = is_superuser.
"""
import datetime
from functools import wraps
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Cotizacion, ItemCotizacion, Producto

# Cotizaciones con intención de compra real (se muestran en la cola igual que
# las demás, pero son las únicas que cuentan en los números comerciales del
# resumen de la dueña). "web-agotado" queda afuera: es un aviso de "avísenme
# cuando haya stock", no una cotización -- alimenta solo la lista de compras.
ORIGENES_COMERCIALES = ["web", "moto"]


def nombre_vendedor(user):
    """Lo que identifica al vendedor en pantalla y en el campo `asesor`. Nunca
    se escribe a mano -- ver el comentario en Cotizacion.asesor."""
    return user.get_full_name() or user.username


def staff_required(vista):
    """Como login_required, pero además exige is_staff (cualquier vendedor de
    mostrador). Sin sesión -> al login del panel, no al de /admin/. Sin
    is_staff -> 403 en vez de delatar que el panel existe."""
    @wraps(vista)
    def envoltorio(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('panel_login')}?next={request.path}")
        if not request.user.is_staff:
            raise PermissionDenied("Esta cuenta no tiene acceso al panel de cotizaciones.")
        return vista(request, *args, **kwargs)
    return envoltorio


class PanelLoginView(LoginView):
    template_name = "panel/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse("panel_cola")


def _wa_link(c, items_txt):
    """wa.me con el mensaje ya redactado -- el vendedor no escribe nada."""
    digitos = "".join(ch for ch in (c.telefono or "") if ch.isdigit())
    if not digitos:
        return ""
    nombre = c.nombre_cliente or ""
    saludo = f"Hola {nombre}," if nombre else "Hola,"
    if c.origen == "web-agotado":
        texto = (f"{saludo} te escribo de SuperMotos La 4ta por tu aviso de "
                 f"disponibilidad de {items_txt or 'un repuesto'}. ¿Seguís interesado/a?")
    elif c.origen == "moto":
        texto = f"{saludo} te escribo de SuperMotos La 4ta por tu interés en una moto. ¿Seguimos?"
    else:
        texto = (f"{saludo} te escribo de SuperMotos La 4ta por tu cotización de "
                 f"{items_txt or 'tus repuestos'}. ¿Seguimos?")
    return f"https://wa.me/{digitos}?text={quote(texto)}"


def _preparar(c):
    """Agrega al objeto (sin guardar nada) lo que la plantilla necesita y que
    no vale la pena calcular en SQL: el link de WhatsApp con el texto listo."""
    items_txt = ", ".join(i.producto.nombre_publico for i in c.items.all())
    c.wa_link = _wa_link(c, items_txt)
    return c


@staff_required
def cola(request):
    # Una sola consulta con el monto ya sumado (mismo patrón que
    # CotizacionAdmin.get_queryset, ver tienda/admin.py) + una segunda para
    # los ítems con su producto (prefetch_related) -- 2 consultas totales,
    # sin importar cuántas cotizaciones haya.
    activas = (Cotizacion.objects
        .exclude(estado__in=["vendida", "perdida"])
        .annotate(monto=Sum(F("items__cantidad") * F("items__precio_unitario")))
        .prefetch_related("items__producto")
        .order_by("creada"))
    sin_atender = [_preparar(c) for c in activas if c.estado == "nueva"]
    en_curso = [_preparar(c) for c in activas if c.estado == "tomada"]
    return render(request, "panel/cola.html", {
        "seccion": "cola",
        "nombre_vendedor": nombre_vendedor(request.user),
        "sin_atender": sin_atender,
        "en_curso": en_curso,
        "motivos": Cotizacion.MOTIVOS_PERDIDA,
    })


@require_POST
@staff_required
def tomar(request, pk):
    # UPDATE condicionado por WHERE estado='nueva': atómico de por sí (una
    # sola sentencia SQL con su propia condición), sin select_for_update ni
    # leer-antes-de-escribir. Si dos vendedores tocan el botón a la vez, la
    # base solo deja pasar UNO -- el WHERE del segundo ya no matchea ninguna
    # fila y su UPDATE afecta 0 filas. No usa .save() a propósito: "tomada" no
    # dispara la validación de motivo_perdida ni toca resuelta_en.
    afectadas = Cotizacion.objects.filter(pk=pk, estado="nueva").update(
        estado="tomada", asesor=nombre_vendedor(request.user), tomada_en=timezone.now())
    if afectadas:
        messages.success(request, "Listo, quedó asignada a vos.")
    else:
        actual = get_object_or_404(Cotizacion, pk=pk)
        if actual.estado == "tomada":
            messages.warning(request, f"Ya la había tomado {actual.asesor}.")
        else:
            messages.info(request, "Esa cotización ya se resolvió.")
    return redirect("panel_cola")


@require_POST
@staff_required
def vender(request, pk):
    # select_for_update + WHERE estado='tomada' vía chequeo explícito: en
    # Postgres (producción) bloquea la fila hasta el commit; en SQLite (local)
    # no hace nada especial pero tampoco falla -- la app ya es de un solo
    # proceso ahí. .save() sí (a diferencia de tomar()): dispara full_clean()
    # y deja que el modelo administre resuelta_en solo (ver Cotizacion.save).
    with transaction.atomic():
        c = get_object_or_404(Cotizacion.objects.select_for_update(), pk=pk)
        if c.estado != "tomada":
            messages.warning(request, "Esa cotización ya no está en curso.")
            return redirect("panel_cola")
        c.estado = "vendida"
        c.save()
    messages.success(request, f"Vendida: {c.nombre_cliente or c.telefono}.")
    return redirect("panel_cola")


@require_POST
@staff_required
def perder(request, pk):
    motivos_validos = dict(Cotizacion.MOTIVOS_PERDIDA)
    motivo = request.POST.get("motivo", "")
    if motivo not in motivos_validos:
        messages.error(request, "Elegí un motivo de la lista.")
        return redirect("panel_cola")
    with transaction.atomic():
        c = get_object_or_404(Cotizacion.objects.select_for_update(), pk=pk)
        if c.estado != "tomada":
            messages.warning(request, "Esa cotización ya no está en curso.")
            return redirect("panel_cola")
        c.estado = "perdida"
        c.motivo_perdida = motivo
        c.save()
    messages.success(request, f"Perdida ({motivos_validos[motivo]}).")
    return redirect("panel_cola")


def _inicio_periodo(periodo):
    ahora = timezone.localtime()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "semana":
        return hoy - datetime.timedelta(days=ahora.weekday())  # lunes
    if periodo == "mes":
        return hoy.replace(day=1)
    return hoy  # "hoy" y cualquier valor no reconocido


def _pct(parte, total):
    return round(parte * 100 / total) if total else None


@staff_required
def resumen(request):
    if not request.user.is_superuser:
        raise PermissionDenied("El resumen es solo para la dueña.")

    periodo = request.GET.get("periodo") if request.GET.get("periodo") in ("hoy", "semana", "mes") else "hoy"
    inicio = _inicio_periodo(periodo)

    comerciales = Cotizacion.objects.filter(origen__in=ORIGENES_COMERCIALES)
    entraron = comerciales.filter(creada__gte=inicio).count()
    # Vendidas/perdidas por cuándo se RESOLVIERON, no por cuándo entraron --
    # para eso está resuelta_en (ver Cotizacion.save): una cotización de hace
    # 2 semanas que se cierra hoy sí debe contar como venta de hoy.
    vendidas_qs = comerciales.filter(estado="vendida", resuelta_en__gte=inicio)
    perdidas_qs = comerciales.filter(estado="perdida", resuelta_en__gte=inicio)
    vendidas, perdidas = vendidas_qs.count(), perdidas_qs.count()
    sin_atender_periodo = comerciales.filter(estado="nueva", creada__gte=inicio).count()
    # El backlog de "ahora" SÍ incluye web-agotado: para el vendedor son
    # llamadas pendientes igual, aunque no cuenten como cotización comercial.
    sin_atender_ahora = Cotizacion.objects.filter(estado="nueva").count()

    motivos_dict = dict(Cotizacion.MOTIVOS_PERDIDA)
    motivos_conteo = list(
        perdidas_qs.values("motivo_perdida").annotate(n=Count("id")).order_by("-n"))
    for fila in motivos_conteo:
        fila["etiqueta"] = motivos_dict.get(fila["motivo_perdida"], "Sin motivo")
    max_motivo = max((f["n"] for f in motivos_conteo), default=0)

    # Lista de compras: cruza los avisos de "no hay stock" (origen
    # web-agotado) con las cotizaciones perdidas por motivo sin_stock,
    # agrupado por producto -- lo que los clientes piden y el almacén no tiene.
    compras_conteo = list(
        ItemCotizacion.objects.filter(
            Q(cotizacion__origen="web-agotado", cotizacion__creada__gte=inicio) |
            Q(cotizacion__estado="perdida", cotizacion__motivo_perdida="sin_stock",
              cotizacion__resuelta_en__gte=inicio)
        ).values("producto_id").annotate(n=Count("id")).order_by("-n")[:15])
    productos_por_id = Producto.objects.in_bulk([f["producto_id"] for f in compras_conteo])
    compras = [{"producto": productos_por_id[f["producto_id"]], "n": f["n"]}
               for f in compras_conteo if f["producto_id"] in productos_por_id]

    # distinct=True: sin esto, una cotización con 2 ítems se contaría 2 veces
    # (el JOIN con items duplica la fila de Cotizacion, no la de venta).
    por_vendedor = list(
        comerciales.filter(estado="vendida", resuelta_en__gte=inicio)
        .exclude(asesor="")
        .values("asesor")
        .annotate(monto=Sum(F("items__cantidad") * F("items__precio_unitario")),
                  n=Count("id", distinct=True))
        .order_by("-monto"))

    return render(request, "panel/resumen.html", {
        "seccion": "resumen",
        "nombre_vendedor": nombre_vendedor(request.user),
        "periodo": periodo,
        "sin_atender_ahora": sin_atender_ahora,
        "entraron": entraron,
        "vendidas": vendidas,
        "perdidas": perdidas,
        "sin_atender_periodo": sin_atender_periodo,
        "pct_vendidas": _pct(vendidas, entraron),
        "pct_perdidas": _pct(perdidas, entraron),
        "motivos_conteo": motivos_conteo,
        "max_motivo": max_motivo,
        "compras": compras,
        "por_vendedor": por_vendedor,
    })
