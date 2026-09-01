from django.core.management.base import BaseCommand
from tienda.importador import importar_excel


class Command(BaseCommand):
    help = "Importa el inventario desde un Excel exportado de Celeste: python manage.py importar_inventario archivo.xlsx"

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--desactivar-faltantes", action="store_true",
                            help="Oculta de la web los productos que ya no vienen en el Excel")

    def handle(self, *args, **opts):
        r = importar_excel(opts["archivo"], desactivar_faltantes=opts["desactivar_faltantes"])
        if not r["ok"]:
            self.stderr.write(self.style.ERROR(r["error"]))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Nuevos: {r['creados']} | Actualizados: {r['actualizados']} | Omitidos: {r['omitidos']}"))
        for d in r["detalles"]:
            self.stdout.write("  " + d)
