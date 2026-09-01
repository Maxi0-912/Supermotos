from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("productos", views.ProductoViewSet, basename="productos")
router.register("motos", views.MotocicletaViewSet, basename="motos")
router.register("cotizaciones", views.CotizacionViewSet, basename="cotizaciones")
router.register("citas", views.CitaViewSet, basename="citas")

urlpatterns = [
    path("", include(router.urls)),
    path("importar-inventario/", views.importar_inventario),
    path("config/", views.configuracion_sitio),
]
