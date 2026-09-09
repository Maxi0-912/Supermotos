from django.db import migrations

# Mapeo acordado: los estados viejos (nueva/contactado/vendida/vencida) no
# alcanzan para el ciclo de vida nuevo (nueva/tomada/vendida/perdida). No hay
# forma de saber CUÁNDO se contactó ni QUIÉN lo hizo con los datos que existen
# hoy -- por eso asesor/tomada_en quedan vacíos en los migrados: es más
# honesto dejarlos en blanco que inventar un dato que no se tiene.
MAPEO = {
    "nueva": "nueva",
    "contactado": "tomada",
    "vendida": "vendida",
    "vencida": "perdida",
}
MOTIVO_VENCIDA = "otro"  # vencida no dice POR QUÉ se perdió; "otro" es lo más honesto


def migrar_estados(apps, schema_editor):
    Cotizacion = apps.get_model("tienda", "Cotizacion")
    for viejo, nuevo in MAPEO.items():
        qs = Cotizacion.objects.filter(estado=viejo)
        if nuevo == "perdida":
            qs.update(estado=nuevo, motivo_perdida=MOTIVO_VENCIDA)
        else:
            qs.update(estado=nuevo)


def revertir(apps, schema_editor):
    Cotizacion = apps.get_model("tienda", "Cotizacion")
    inverso = {v: k for k, v in MAPEO.items()}
    for nuevo, viejo in inverso.items():
        Cotizacion.objects.filter(estado=nuevo).update(estado=viejo, motivo_perdida="")


class Migration(migrations.Migration):

    dependencies = [
        ('tienda', '0007_cotizacion_ciclo_de_vida'),
    ]

    operations = [
        migrations.RunPython(migrar_estados, revertir),
    ]
