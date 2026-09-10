from rest_framework import serializers
from .models import (Producto, Cotizacion, ItemCotizacion, Cita,
                     Motocicleta, ConfiguracionSitio)


class FotoSerializerMixin:
    """Foto elegida a mano por Ana (imagen subida o imagen_url). Vacío si
    todavía no eligió ninguna: el frontend muestra una placa."""
    def get_foto(self, obj):
        if not obj.foto:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.foto) if request else obj.foto


class ProductoSerializer(FotoSerializerMixin, serializers.ModelSerializer):
    stock = serializers.IntegerField(source="stock_web", read_only=True)
    # nombre_publico: si el nombre parseado quedó ilegible (descripción de
    # Celeste que era solo un código), la tarjeta recibe un rótulo armado con
    # marca + referencia + modelos en vez de un código suelto. Ver Producto.
    nombre = serializers.CharField(source="nombre_publico", read_only=True)
    foto = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = ["id", "codigo_celeste", "referencia", "nombre", "categoria",
                  "marca", "precio", "stock", "modelos_compatibles", "foto"]


class MotocicletaSerializer(FotoSerializerMixin, serializers.ModelSerializer):
    foto = serializers.SerializerMethodField()

    class Meta:
        model = Motocicleta
        fields = ["id", "nombre", "marca", "precio", "cilindraje", "categoria",
                  "descripcion", "foto", "destacada", "disponible"]


class ConfiguracionSitioSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracionSitio
        fields = ["whatsapp_asesor", "nombre_asesor", "telefono_fijo", "direccion"]


class ItemCotizacionSerializer(serializers.ModelSerializer):
    producto_id = serializers.PrimaryKeyRelatedField(
        source="producto", queryset=Producto.objects.filter(activo=True))
    nombre = serializers.CharField(source="producto.nombre_publico", read_only=True)

    class Meta:
        model = ItemCotizacion
        fields = ["producto_id", "nombre", "cantidad", "precio_unitario"]
        read_only_fields = ["precio_unitario"]


class CotizacionSerializer(serializers.ModelSerializer):
    items = ItemCotizacionSerializer(many=True)
    total = serializers.ReadOnlyField()

    class Meta:
        model = Cotizacion
        fields = ["id", "nombre_cliente", "telefono", "origen", "estado", "items", "total", "creada"]
        read_only_fields = ["estado", "creada"]

    def create(self, validated_data):
        items = validated_data.pop("items")
        cot = Cotizacion.objects.create(**validated_data)
        for it in items:
            producto = it["producto"]
            ItemCotizacion.objects.create(
                cotizacion=cot, producto=producto,
                cantidad=it.get("cantidad", 1),
                precio_unitario=producto.precio)  # precio del servidor, no del cliente
        return cot


class CitaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cita
        fields = ["id", "nombre_cliente", "telefono", "servicio", "moto",
                  "fecha", "hora", "estado", "creada"]
        read_only_fields = ["estado", "creada"]
