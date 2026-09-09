import importlib
import io
import tempfile
from datetime import timedelta
from pathlib import Path

from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .admin import CotizacionAdmin, PerderForm, TomarForm
from .models import (Cotizacion, ConfiguracionSitio, ImportacionInventario,
                     ItemCotizacion, Producto)
from .templatetags.almacen_avisos import avisos_almacen


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


class WhatsAppAsesorTests(TestCase):
    """C.2 — validación del número del asesor (el que rompe todo si está mal)."""

    def test_normaliza_a_digitos(self):
        c = ConfiguracionSitio(whatsapp_asesor="+57 (300) 123-4567")
        c.full_clean()
        self.assertEqual(c.whatsapp_asesor, "573001234567")
        self.assertTrue(c.whatsapp_valido)

    def test_vacio_es_valido_de_form_pero_no_plausible(self):
        c = ConfiguracionSitio(whatsapp_asesor="")
        c.full_clean()  # no rompe: el frontend degrada
        self.assertFalse(c.whatsapp_valido)

    def test_numero_corto_se_rechaza(self):
        for malo in ["57", "300123", "12345"]:
            with self.assertRaises(ValidationError, msg=malo) as ctx:
                ConfiguracionSitio(whatsapp_asesor=malo).full_clean()
            self.assertIn("whatsapp_asesor", ctx.exception.message_dict)

    def test_numero_largo_se_rechaza(self):
        with self.assertRaises(ValidationError):
            ConfiguracionSitio(whatsapp_asesor="1" * 16).full_clean()

    def test_no_hay_default_trampa(self):
        # instalación nueva: get_or_create no debe dejar "57" ni nada inválido
        c, _ = ConfiguracionSitio.objects.get_or_create(pk=1)
        self.assertEqual(c.whatsapp_asesor, "")
        self.assertFalse(c.whatsapp_valido)


class AvisosAdminTests(TestCase):
    """C.2 — la franja de avisos del admin."""

    def _con_whatsapp_ok(self):
        ConfiguracionSitio.objects.update_or_create(
            pk=1, defaults={"whatsapp_asesor": "573001234567",
                            "telefono_fijo": "(602) 838 12 34"})

    def test_avisa_whatsapp_mal_configurado(self):
        self._con_whatsapp_ok()
        ImportacionInventario.objects.create(creados=1)  # fecha = ahora
        self.assertEqual(avisos_almacen(), "")

        ConfiguracionSitio.objects.filter(pk=1).update(whatsapp_asesor="57")
        self.assertIn("WhatsApp del asesor", avisos_almacen())

    def test_combo_b_avisa_whatsapp_y_alterno_juntos(self):
        # Instalación nueva: sin WhatsApp y sin contacto alterno -> un solo
        # aviso que nombra las dos faltas.
        ConfiguracionSitio.objects.update_or_create(pk=1, defaults={
            "whatsapp_asesor": "", "telefono_fijo": "", "direccion": ""})
        html = avisos_almacen()
        self.assertIn("falta el WhatsApp del asesor", html)
        self.assertIn("no tiene forma de contactar al almacén", html)

    def test_con_alterno_no_menciona_falta_de_alterno(self):
        ConfiguracionSitio.objects.update_or_create(pk=1, defaults={
            "whatsapp_asesor": "", "telefono_fijo": "3001112222", "direccion": ""})
        html = avisos_almacen()
        self.assertNotIn("no tiene forma de contactar", html)
        self.assertIn("mostrando el teléfono/dirección en su lugar", html)

    def test_avisa_inventario_viejo(self):
        self._con_whatsapp_ok()
        imp = ImportacionInventario.objects.create(creados=1)
        ImportacionInventario.objects.filter(pk=imp.pk).update(
            fecha=timezone.now() - timedelta(hours=72))
        html = avisos_almacen()
        self.assertIn("no se actualiza hace 72 horas", html)

    def test_sin_importaciones_tambien_avisa(self):
        self._con_whatsapp_ok()
        self.assertIn("no se importó ningún inventario", avisos_almacen())

    def test_cada_aviso_enlaza_a_su_pantalla(self):
        # WhatsApp mal + sin inventario: los dos avisos, con sus dos enlaces.
        ConfiguracionSitio.objects.update_or_create(
            pk=1, defaults={"whatsapp_asesor": ""})
        html = avisos_almacen()
        self.assertIn(
            'href="%s"' % reverse("admin:tienda_configuracionsitio_changelist"), html)
        self.assertIn(
            'href="%s"' % reverse("admin:tienda_importacioninventario_subir"), html)

    # el admin renderiza {% static %} y en prod usa el manifest de whitenoise
    # (que necesita collectstatic); en tests basta el almacenamiento simple.
    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_banner_visible_en_el_admin(self):
        User = get_user_model()
        User.objects.create_superuser("ana", "ana@almacen.co", "x")
        self.client.force_login(User.objects.get(username="ana"))
        # sin config -> el aviso debe salir en el HTML del index del admin
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No hay datos de contacto configurados")


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    # el redirect del admin renderiza {% static %}; en prod usa el manifest de
    # whitenoise (necesita collectstatic), en tests basta el simple.
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ExcelNoSePersisteTests(TestCase):
    """Seguridad: el Excel de Celeste (costos y márgenes del negocio) no debe
    quedar en disco ni accesible una vez procesado."""

    def _xlsx(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Código", "Descripcion", "Público", "Dispo"])
        ws.append(["C-001", "17211-KRH-780 FILTRO DE AIRE (CB110)", 35000, 8])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _ana(self):
        User = get_user_model()
        User.objects.create_superuser("ana", "ana@almacen.co", "x")
        self.client.force_login(User.objects.get(username="ana"))

    def test_admin_subir_importa_pero_borra_el_archivo(self):
        self._ana()
        resp = self.client.post(
            reverse("admin:tienda_importacioninventario_subir"),
            {"archivo": SimpleUploadedFile("celeste.xlsx", self._xlsx())},
            follow=True)
        self.assertEqual(resp.status_code, 200)
        reg = ImportacionInventario.objects.get()
        self.assertEqual(reg.creados, 1)                    # sí se importó
        self.assertFalse(reg.archivo)                       # pero no quedó guardado
        self.assertEqual(
            list(Path(settings.MEDIA_ROOT).glob("importaciones/*")), [])

    def test_archivo_invalido_no_revienta_y_no_queda_en_disco(self):
        self._ana()
        resp = self.client.post(
            reverse("admin:tienda_importacioninventario_subir"),
            {"archivo": SimpleUploadedFile("no-es-excel.xlsx", b"esto no es un xlsx")},
            follow=True)
        self.assertEqual(resp.status_code, 200)                    # sin 500
        self.assertContains(resp, "No se pudo abrir el archivo")   # error claro para Ana
        self.assertEqual(
            list(Path(settings.MEDIA_ROOT).glob("importaciones/*")), [])
