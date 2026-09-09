from django.db.models import Q
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import (Producto, Cotizacion, Cita, ImportacionInventario,
                     Motocicleta, ConfiguracionSitio)
from .serializers import (ProductoSerializer, CotizacionSerializer, CitaSerializer,
                          MotocicletaSerializer, ConfiguracionSitioSerializer)
from .importador import importar_excel
from . import busqueda


# Las categorías reales de Celeste son casi todas "Repuestos original" /
# "Repuestos generico" y no sirven para filtrar por tipo de repuesto. Los
# chips de la página (Frenos, Filtros, ...) se mapean aquí a palabras clave
# reales que sí aparecen en los nombres del inventario.
CHIP_KEYWORDS = {
    "frenos": ["freno", "pastilla", "banda", "disco", "zapata"],
    "filtros": ["filtro"],
    "aceites": ["aceite", "lubricante"],
    "electrico": ["bujia", "bateria", "cdi", "bobina", "farola", "direccional",
                  "stop", "regulador", "estator"],
    "transmision": ["arrastre", "cadena", "piñon", "sprocket", "clutch",
                     "embrague", "corona", "estrella"],
    "llantas": ["llanta", "neumatico", "rin", "caucho", "tubo"],
}


class ProductoViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/productos/?buscar=frenos+para+mi+cb110  -> motor conversacional (tienda/busqueda.py)
    GET /api/productos/?categoria=frenos                -> chips de la página (CHIP_KEYWORDS)
    GET /api/productos/?modelo=CB160F                   -> filtro directo por modelo
    """
    serializer_class = ProductoSerializer

    def get_queryset(self):
        texto = self.request.query_params.get("buscar", "").strip()
        categoria = self.request.query_params.get("categoria", "").strip().lower()
        modelo = self.request.query_params.get("modelo", "").strip()
        # con_stock filtra de verdad (excluye agotados); priorizar_stock solo
        # reordena (los agotados quedan al final, sin desaparecer). Antes un
        # mismo parámetro con_stock hacía una cosa acá y otra en la rama de
        # abajo -- separados para que cada uno signifique una sola cosa.
        con_stock = bool(self.request.query_params.get("con_stock", ""))
        priorizar_stock = bool(self.request.query_params.get("priorizar_stock", ""))

        if texto:
            # Motor conversacional: entiende pieza + modelo, sinónimos de
            # taller y ~50 modelos reales del inventario. Por defecto NO
            # excluye los agotados (los reordena al final, priorizar_stock)
            # para que el bot pueda ofrecer "avísenme cuando llegue" en vez
            # de decir que no existen.
            productos, _piezas, _modelos, uso_fallback = busqueda.buscar(
                texto, con_stock=con_stock, priorizar_stock=priorizar_stock)
            # Se guarda para que list() lo exponga como header (ver abajo):
            # así el bot puede matizar "no encontré exactamente eso, pero..."
            # sin cambiar la forma del JSON (sigue siendo una lista plana).
            self._uso_fallback = uso_fallback
            return productos

        qs = Producto.objects.filter(activo=True)
        if modelo:
            m = modelo.replace(" ", "").replace("-", "")
            qs = qs.filter(Q(modelos_compatibles__icontains=modelo) |
                           Q(nombre__icontains=modelo) |
                           Q(nombre__icontains=m))
        if categoria:
            palabras = CHIP_KEYWORDS.get(categoria)
            if palabras:
                sub = Q()
                for palabra in palabras:
                    sub |= Q(nombre__icontains=palabra)
                qs = qs.filter(sub)
            else:
                # categoría libre (no es uno de los chips): compatibilidad
                # con el campo `categoria` real de Celeste.
                qs = qs.filter(categoria__icontains=categoria)
        if con_stock:
            qs = qs.filter(stock__gt=0)
        return qs[:60]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if getattr(self, "_uso_fallback", False):
            response["X-Busqueda-Fallback"] = "1"
        return response


class MotocicletaViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/motos/?categoria=naked&destacada=1
    Catálogo de motos NUEVAS del concesionario (separado de los repuestos)."""
    serializer_class = MotocicletaSerializer

    def get_queryset(self):
        qs = Motocicleta.objects.filter(disponible=True)
        categoria = self.request.query_params.get("categoria", "").strip()
        destacada = self.request.query_params.get("destacada", "")
        if categoria:
            qs = qs.filter(categoria__icontains=categoria)
        if destacada:
            qs = qs.filter(destacada=True)
        return qs


@api_view(["GET"])
def configuracion_sitio(request):
    """GET /api/config/ -> {whatsapp_asesor, nombre_asesor}
    Fila única (singleton); se crea con los valores por defecto del modelo
    si todavía no existe, así el frontend nunca queda sin número."""
    config, _creada = ConfiguracionSitio.objects.get_or_create(pk=1)
    return Response(ConfiguracionSitioSerializer(config).data)


class CotizacionViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """POST /api/cotizaciones/  (el bot y la web crean cotizaciones)"""
    queryset = Cotizacion.objects.all()
    serializer_class = CotizacionSerializer
    throttle_scope = 'escritura_publica'


class CitaViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """POST /api/citas/"""
    queryset = Cita.objects.all()
    serializer_class = CitaSerializer
    throttle_scope = 'escritura_publica'


@api_view(["POST"])
@permission_classes([IsAdminUser])
@parser_classes([MultiPartParser])
def importar_inventario(request):
    """POST /api/importar-inventario/ con archivo=<excel de Celeste>.
    Solo usuarios administradores (la dueña, desde el panel)."""
    archivo = request.FILES.get("archivo")
    if not archivo:
        return Response({"error": "Adjunta el archivo Excel exportado de Celeste en el campo 'archivo'."},
                        status=status.HTTP_400_BAD_REQUEST)
    registro = ImportacionInventario.objects.create(archivo=archivo)
    try:
        resultado = importar_excel(registro.archivo.path)
    finally:
        # El Excel de Celeste lleva costos y márgenes del negocio. Una vez
        # procesado no aporta nada guardarlo, y dejarlo en MEDIA_ROOT es un
        # riesgo (basta un cambio de DEBUG o de urls.py para exponerlo). Se
        # borra siempre, incluso si la importación falló.
        registro.archivo.delete(save=False)
        registro.archivo = ""
    registro.creados = resultado.get("creados", 0)
    registro.actualizados = resultado.get("actualizados", 0)
    registro.errores = "\n".join(resultado.get("detalles", [])) or resultado.get("error", "")
    registro.save()
    codigo = status.HTTP_200_OK if resultado.get("ok") else status.HTTP_400_BAD_REQUEST
    return Response(resultado, status=codigo)
