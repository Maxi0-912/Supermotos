"""Re-parsea el nombre de los ~3.088 productos ya cargados aplicando el parser
extendido (bug de nombres ilegibles en producción).

Antes de este cambio, con el inventario real cargado, ~140 tarjetas mostraban
el código de proveedor dentro del nombre ("VH10384 KIT CILINDRO GRIS XR150L"),
una referencia pegada a la primera palabra ("...D41PISTON DE VACIO...") o el
nombre entero era un código. La corrección vive en tienda.models.parsear_
descripcion; esta migración la aplica a las filas que ya estaban en la base
(el importador solo re-parsea al volver a subir el Excel).

Se importa parsear_descripcion de la app a propósito: el objetivo es aplicar
"el parser tal como quedó en este punto" a los datos viejos. Si el parser
cambia más adelante, ese cambio llevará su propia migración de datos; esta no
se re-ejecuta.
"""
import unicodedata

from django.db import migrations

from tienda.models import parsear_descripcion


# Copia local de normalizar() (tienda/busqueda.py), igual criterio que 0005:
# la fórmula de texto_busqueda no debe cambiar bajo esta migración si algún
# día se reescribe normalizar().
def _normalizar(texto):
    t = str(texto or "").lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def reparsear(apps, schema_editor):
    Producto = apps.get_model("tienda", "Producto")
    cambiados = []
    for p in Producto.objects.all().iterator():
        origen = p.descripcion_original or p.nombre
        info = parsear_descripcion(origen)
        nombre = info["nombre"][:250].strip().upper()
        modelos = ", ".join(info["modelos"])[:250]
        referencia = info["referencia"][:40] or p.referencia
        nuevo_texto = _normalizar(
            f"{referencia} {nombre} {modelos} {p.categoria}")
        if (nombre, modelos, referencia, nuevo_texto) != (
                p.nombre, p.modelos_compatibles, p.referencia, p.texto_busqueda):
            p.nombre = nombre
            p.modelos_compatibles = modelos
            p.referencia = referencia
            p.texto_busqueda = nuevo_texto
            cambiados.append(p)
    Producto.objects.bulk_update(
        cambiados,
        ["nombre", "modelos_compatibles", "referencia", "texto_busqueda"],
        batch_size=500)


def revertir(apps, schema_editor):
    # No hay vuelta atrás fiel: el nombre viejo (con el código incrustado) no
    # se guarda en ninguna parte. descripcion_original queda intacta, así que
    # volver a subir el Excel regenera el estado que haga falta.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tienda", "0009_configuracionsitio_contacto"),
    ]

    operations = [
        migrations.RunPython(reparsear, revertir),
    ]
