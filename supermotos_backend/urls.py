from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse


def frontend(request):
    """Sirve web_frontend.html directamente en el mismo puerto que la API,
    para no depender de Live Server ni de CORS en desarrollo."""
    return FileResponse(open(settings.BASE_DIR / 'web_frontend.html', 'rb'), content_type='text/html')


urlpatterns = [
    path('', frontend),
    path('admin/', admin.site.urls),
    path('api/', include('tienda.urls')),
]

# static() SOLO devuelve rutas con DEBUG=True: en producción MEDIA_URL no se
# sirve por Django y whitenoise sirve únicamente STATIC_ROOT, no MEDIA_ROOT.
# Es a propósito -- lo subido a media/ (el Excel de Celeste ya se borra tras
# importarse; ver tienda/views.py) no debe quedar accesible por URL. Si algún
# día hacen falta imágenes subidas en producción, se resuelve con
# almacenamiento externo (S3 / volumen), no abriendo esta ruta.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
