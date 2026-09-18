from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views_panel

urlpatterns = [
    path("", views_panel.cola),  # / y /cola/ son lo mismo -- la pantalla de todos los días
    path("cola/", views_panel.cola, name="panel_cola"),
    path("resumen/", views_panel.resumen, name="panel_resumen"),
    path("cotizacion/<int:pk>/tomar/", views_panel.tomar, name="panel_tomar"),
    path("cotizacion/<int:pk>/vender/", views_panel.vender, name="panel_vender"),
    path("cotizacion/<int:pk>/perder/", views_panel.perder, name="panel_perder"),
    path("login/", views_panel.PanelLoginView.as_view(), name="panel_login"),
    # POST-only (ver el botón "Salir" en panel/shell.html): evita que un link
    # o un prefetch del navegador cierre la sesión sin que nadie lo pida.
    path("logout/", LogoutView.as_view(next_page="panel_login"), name="panel_logout"),
]
