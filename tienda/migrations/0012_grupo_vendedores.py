"""Crea el grupo 'Vendedores' (auth.Group) que usa tienda/views_panel.py para
decidir quién entra a la cola del panel -- ver GRUPO_VENDEDORES ahí. A
propósito no se usa is_staff/is_superuser para esto: is_staff es la puerta de
/admin/ (catálogo, configuración del sitio), que un vendedor de mostrador no
tiene por qué poder abrir.
"""
from django.db import migrations

NOMBRE_GRUPO = "Vendedores"


def crear_grupo(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=NOMBRE_GRUPO)


def borrar_grupo(apps, schema_editor):
    # Solo si sigue vacío: si para cuando se revierte esta migración ya hay
    # vendedores asignados, borrar el grupo los dejaría sin acceso al panel
    # sin ningún aviso -- mejor dejarlo aunque la migración se revierta.
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=NOMBRE_GRUPO, user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tienda", "0011_cotizacion_resuelta_en"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
