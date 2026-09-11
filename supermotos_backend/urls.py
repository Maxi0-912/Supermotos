from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.http import FileResponse
from django.views.static import serve as _serve_media


def frontend(request):
    """Sirve web_frontend.html directamente en el mismo puerto que la API,
    para no depender de Live Server ni de CORS en desarrollo."""
    return FileResponse(open(settings.BASE_DIR / 'web_frontend.html', 'rb'), content_type='text/html')


urlpatterns = [
    path('', frontend),
    path('admin/', admin.site.urls),
    path('api/', include('tienda.urls')),
]

# WhiteNoise sirve solo STATIC_ROOT, no MEDIA_ROOT. Antes /media/ solo se
# servía con DEBUG=True (django.conf.urls.static.static), así que una foto
# subida por Ana no cargaba en producción. Ahora se sirve SIEMPRE con la vista
# `serve` de Django (no está atada a DEBUG; el helper static() sí lo estaba),
# leyendo desde MEDIA_ROOT -- que en producción es un volumen persistente
# (ver settings.MEDIA_ROOT). Es seguro: el Excel de Celeste ya no queda en
# media/ (se borra tras importarse, ver tienda/views.py y tienda/admin.py),
# así que ahí solo hay fotos de producto/moto. `serve` valida la ruta contra
# traversal. Para tráfico alto conviene un CDN/volumen servido por el edge,
# pero para este catálogo el worker de gunicorn sirve las pocas fotos sin
# problema; migrar a object storage sería cambiar STORAGES, no esta ruta.
def _media(request, path):
    # Resuelve MEDIA_ROOT en cada request (no al importar): así respeta un
    # override en tests y un cambio de la variable sin reiniciar.
    return _serve_media(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns += [re_path(r'^media/(?P<path>.*)$', _media)]
