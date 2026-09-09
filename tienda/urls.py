from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("productos", views.ProductoViewSet, basename="productos")
router.register("motos", views.MotocicletaViewSet, basename="motos")
router.register("cotizaciones", views.CotizacionViewSet, basename="cotizaciones")
# El agendamiento de citas se descartó (ver Fase 3, Parte A): el bot ya no
# ofrece este flujo y ningún vendedor revisa esta bandeja. El modelo, la
# migración y el ViewSet se dejan intactos en el código -- solo se retira
# del router para no exponer un POST anónimo que alimenta una tabla muerta.
# Para reactivarlo: descomentar esta línea.
# router.register("citas", views.CitaViewSet, basename="citas")

urlpatterns = [
    path("", include(router.urls)),
    path("importar-inventario/", views.importar_inventario),
    path("config/", views.configuracion_sitio),
]
