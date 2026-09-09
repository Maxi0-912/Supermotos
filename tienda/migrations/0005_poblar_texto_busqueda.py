import unicodedata

from django.db import migrations


# Copia local de normalizar() (tienda/busqueda.py): las migraciones no deben
# depender de código de la app que puede cambiar después -- si algún día se
# reescribe normalizar(), esta migración debe seguir poblando los datos tal
# como se pensó en este momento, no con la lógica futura.
def _normalizar(texto):
    t = str(texto or "").lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def poblar_texto_busqueda(apps, schema_editor):
    Producto = apps.get_model("tienda", "Producto")
    objetos = []
    for p in Producto.objects.all().iterator():
        p.texto_busqueda = _normalizar(
            f"{p.referencia} {p.nombre} {p.modelos_compatibles} {p.categoria}")
        objetos.append(p)
    Producto.objects.bulk_update(objetos, ["texto_busqueda"], batch_size=500)


def revertir(apps, schema_editor):
    # No hace falta vaciar el campo al revertir: la migración anterior
    # (0004) ya lo elimina de la tabla.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tienda', '0004_texto_busqueda_persistido'),
    ]

    operations = [
        migrations.RunPython(poblar_texto_busqueda, revertir),
    ]
