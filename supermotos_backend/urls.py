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
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
