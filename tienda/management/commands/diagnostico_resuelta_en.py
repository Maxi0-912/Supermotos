"""Diagnóstico de SOLO LECTURA para decidir el backfill de resuelta_en (Paso A
antes de aplicar la migración 0012_backfill_resuelta_en). No escribe nada en
la base -- ningún .save()/.update()/.create() en todo el comando.

Uso: python manage.py diagnostico_resuelta_en
"""
from django.core.management.base import BaseCommand
from django.db.models import Max, Min

from tienda.models import Cotizacion


class Command(BaseCommand):
    help = ("Solo lectura: cuenta cotizaciones por estado y mide cuántas "
            "vendida/perdida quedarían sin resuelta_en tras el backfill.")

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Cotizaciones por estado"))
        total = 0
        for valor, etiqueta in Cotizacion.ESTADOS:
            n = Cotizacion.objects.filter(estado=valor).count()
            total += n
            self.stdout.write(f"  {etiqueta:10s} ({valor:8s}): {n}")
        self.stdout.write(f"  {'TOTAL':21s}: {total}")
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING(
            "Vendida/perdida sin resuelta_en (candidatas al backfill de la 0012)"))
        sin_fecha = Cotizacion.objects.filter(
            estado__in=["vendida", "perdida"], resuelta_en__isnull=True)
        n_sin_fecha = sin_fecha.count()
        self.stdout.write(f"  Total: {n_sin_fecha}")

        if not n_sin_fecha:
            self.stdout.write(
                "  Nada que backfillear: todas las vendida/perdida ya tienen resuelta_en.")
            return

        con_tomada_en = sin_fecha.exclude(tomada_en__isnull=True).count()
        sin_tomada_en = n_sin_fecha - con_tomada_en
        self.stdout.write(f"  Con tomada_en (se backfillean con ese valor): {con_tomada_en}")
        self.stdout.write(
            f"  Sin tomada_en (quedan en NULL a propósito, ver 0012): {sin_tomada_en}")

        rango = sin_fecha.aggregate(mas_vieja=Min("creada"), mas_nueva=Max("creada"))
        self.stdout.write(f"  creada más antigua en este conjunto:  {rango['mas_vieja']}")
        self.stdout.write(f"  creada más reciente en este conjunto: {rango['mas_nueva']}")
