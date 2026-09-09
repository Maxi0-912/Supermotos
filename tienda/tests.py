import importlib

from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.client import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .admin import CotizacionAdmin, PerderForm, TomarForm
from .models import Cotizacion, ItemCotizacion, Producto


def _producto(precio=1000, **extra):
    base = dict(codigo_celeste=f"P{Producto.objects.count() + 1:04d}",
                nombre="Repuesto de prueba", precio=precio, stock=10)
    base.update(extra)
    return Producto.objects.create(**base)


class CicloVidaCotizacionTests(TestCase):
    """B — flujo completo de estados: nueva -> tomada -> vendida / perdida."""

    def setUp(self):
        self.p = _producto(precio=1500)

    def _cotizacion(self, **extra):
        c = Cotizacion.objects.create(nombre_cliente="Cliente", telefono="3001112233", **extra)
        ItemCotizacion.objects.create(cotizacion=c, producto=self.p, cantidad=2, precio_unitario=1500)
        return c

    def test_flujo_nueva_tomada_vendida(self):
        c = self._cotizacion()
        self.assertEqual(c.estado, "nueva")
        self.assertEqual(c.asesor, "")
        self.assertIsNone(c.tomada_en)

        # tomada: asesor + tomada_en quedan registrados (evita doble atención)
        c.estado = "tomada"
        c.asesor = "Laura"
        c.tomada_en = timezone.now()
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.estado, "tomada")
        self.assertEqual(c.asesor, "Laura")
        self.assertIsNotNone(c.tomada_en)

        # vendida
        c.estado = "vendida"
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.estado, "vendida")

    def test_perdida_exige_motivo_en_el_modelo(self):
        """No solo en la interfaz: clean()/save() del modelo lo rechazan."""
        c = self._cotizacion()
        c.estado = "perdida"
        with self.assertRaises(ValidationError) as ctx:
            c.full_clean()
        self.assertIn("motivo_perdida", ctx.exception.message_dict)

        with self.assertRaises(ValidationError):
            c.save()

        # sigue siendo "nueva" en la base: el save() abortó
        c.refresh_from_db()
        self.assertEqual(c.estado, "nueva")

    def test_perdida_con_motivo_valido(self):
        c = self._cotizacion()
        c.estado = "perdida"
        c.motivo_perdida = "precio"
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.estado, "perdida")
        self.assertEqual(c.motivo_perdida, "precio")

    def test_accion_masiva_perder_sin_motivo_no_valida(self):
        self.assertFalse(PerderForm({}).is_valid())
        self.assertTrue(PerderForm({"motivo_perdida": "no_contesto"}).is_valid())
        self.assertFalse(PerderForm({"motivo_perdida": "inexistente"}).is_valid())

    def test_accion_masiva_tomar_exige_asesor(self):
        self.assertFalse(TomarForm({}).is_valid())
        self.assertTrue(TomarForm({"asesor": "Laura"}).is_valid())

    def test_salir_de_perdida_limpia_el_motivo(self):
        """Motivo huérfano: vender/tomar una cotización antes perdida no debe
        dejar el motivo_perdida pegado (contamina el dato de pérdidas)."""
        c = self._cotizacion()
        c.estado = "perdida"
        c.motivo_perdida = "no_contesto"
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.motivo_perdida, "no_contesto")

        c.estado = "vendida"
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.estado, "vendida")
        self.assertEqual(c.motivo_perdida, "")

    def test_origen_se_conserva(self):
        c = self._cotizacion(origen="web-agotado")
        c.estado = "tomada"
        c.asesor = "Laura"
        c.tomada_en = timezone.now()
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.origen, "web-agotado")


class AdminListaSinNMasUnoTests(TestCase):
    """La lista del admin muestra total / #ítems con anotación, no N+1."""

    def setUp(self):
        self.p1 = _producto(precio=1000)
        self.p2 = _producto(precio=500)
        for i in range(5):
            c = Cotizacion.objects.create(telefono=f"30000000{i}")
            ItemCotizacion.objects.create(cotizacion=c, producto=self.p1, cantidad=2, precio_unitario=1000)
            ItemCotizacion.objects.create(cotizacion=c, producto=self.p2, cantidad=1, precio_unitario=500)

    def test_una_sola_consulta_para_total_y_items(self):
        admin = CotizacionAdmin(Cotizacion, __import__("django.contrib.admin", fromlist=["site"]).site)
        request = RequestFactory().get("/admin/tienda/cotizacion/")
        request.user = get_user_model()(is_superuser=True, is_staff=True)
        qs = admin.get_queryset(request)

        with CaptureQueriesContext(connection) as cap:
            filas = list(qs)
            totales = [(f.monto_total, f.num_items) for f in filas]
        self.assertEqual(len(cap), 1, "debería resolverse en una sola consulta")
        self.assertEqual(totales, [(2500, 2)] * 5)

    def test_orden_por_estado_y_fecha(self):
        Cotizacion.objects.all().delete()
        vendida = Cotizacion.objects.create(telefono="1", estado="vendida")
        nueva = Cotizacion.objects.create(telefono="2", estado="nueva")
        tomada = Cotizacion.objects.create(telefono="3", estado="tomada", asesor="L",
                                           tomada_en=timezone.now())
        admin = CotizacionAdmin(Cotizacion, __import__("django.contrib.admin", fromlist=["site"]).site)
        request = RequestFactory().get("/")
        request.user = get_user_model()(is_superuser=True, is_staff=True)
        ids = list(admin.get_queryset(request).values_list("id", flat=True))
        self.assertEqual(ids, [nueva.id, tomada.id, vendida.id])


class MigracionEstadosTests(TestCase):
    """0008: contactado->tomada, vencida->perdida(motivo otro); sin perder filas."""

    def setUp(self):
        self.mig = importlib.import_module("tienda.migrations.0008_migrar_estados_cotizacion")
        self.p = _producto()

    def _con_estado_viejo(self, estado):
        c = Cotizacion.objects.create(nombre_cliente="Migrado", telefono="3150000000")
        ItemCotizacion.objects.create(cotizacion=c, producto=self.p, cantidad=3, precio_unitario=1000)
        # .update() evita el full_clean() del modelo nuevo y deja el estado viejo crudo
        Cotizacion.objects.filter(pk=c.pk).update(estado=estado)
        return c.pk

    def test_mapeo_y_conservacion_de_registros(self):
        pks = {
            "nueva": self._con_estado_viejo("nueva"),
            "contactado": self._con_estado_viejo("contactado"),
            "vendida": self._con_estado_viejo("vendida"),
            "vencida": self._con_estado_viejo("vencida"),
        }
        antes = Cotizacion.objects.count()

        self.mig.migrar_estados(global_apps, None)

        self.assertEqual(Cotizacion.objects.count(), antes, "no se pierde ninguna fila")
        self.assertEqual(Cotizacion.objects.get(pk=pks["nueva"]).estado, "nueva")
        self.assertEqual(Cotizacion.objects.get(pk=pks["contactado"]).estado, "tomada")
        self.assertEqual(Cotizacion.objects.get(pk=pks["vendida"]).estado, "vendida")

        vencida = Cotizacion.objects.get(pk=pks["vencida"])
        self.assertEqual(vencida.estado, "perdida")
        self.assertEqual(vencida.motivo_perdida, "otro")

        # datos de cliente / ítems intactos
        for pk in pks.values():
            c = Cotizacion.objects.get(pk=pk)
            self.assertEqual(c.nombre_cliente, "Migrado")
            self.assertEqual(c.telefono, "3150000000")
            self.assertEqual(c.items.count(), 1)
            self.assertEqual(c.items.first().cantidad, 3)

    def test_reversible(self):
        pk = self._con_estado_viejo("vencida")
        self.mig.migrar_estados(global_apps, None)
        self.assertEqual(Cotizacion.objects.get(pk=pk).estado, "perdida")
        self.mig.revertir(global_apps, None)
        revertida = Cotizacion.objects.get(pk=pk)
        self.assertEqual(revertida.estado, "vencida")
        self.assertEqual(revertida.motivo_perdida, "")
