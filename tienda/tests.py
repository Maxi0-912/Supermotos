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

from .admin import CotizacionAdmin, NombreLegibleFilter, PerderForm, TomarForm
from .importador import importar_excel
from .models import (Cotizacion, ConfiguracionSitio, ImportacionInventario,
                     ItemCotizacion, Producto, nombre_es_ilegible,
                     parsear_descripcion)
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


class ParsearDescripcionTests(TestCase):
    """Bug de nombres ilegibles en produccion (inventario real cargado).
    Paso 2: el parser extendido. Cada caso viene de una descripcion real de
    Celeste vista en el catalogo de 3.088 productos."""

    def _nombre(self, desc):
        return parsear_descripcion(desc)["nombre"].strip().upper()

    # --- los tres casos del reporte -------------------------------------
    def test_dos_referencias_encadenadas_al_inicio(self):
        info = parsear_descripcion(
            "16111-K38-901- 16111-K43-D41PISTON DE VACIO CARBURADOR DIAFRAGMA (TODAS LAS MOTOS)")
        self.assertEqual(info["referencia"], "16111-K38-901")
        self.assertEqual(
            info["nombre"],
            "PISTON DE VACIO CARBURADOR DIAFRAGMA (TODAS LAS MOTOS)")

    def test_nombre_que_era_solo_codigo_queda_vacio(self):
        for solo_codigo in ["3340B-AAH-001S", "3345B-AAH-001S", "52400-KWP-901",
                            "98059-58916", "K12913HF100DS"]:
            info = parsear_descripcion(solo_codigo)
            self.assertEqual(info["nombre"], "", solo_codigo)

    def test_codigo_de_proveedor_al_inicio_se_saca_del_nombre(self):
        info = parsear_descripcion("VH10384 KIT CILINDRO GRIS XR150L")
        self.assertEqual(info["nombre"], "KIT CILINDRO GRIS XR150L")
        self.assertEqual(info["referencia"], "VH10384")
        self.assertEqual(
            self._nombre("NYS06132 LLANTA TRAS 90/90-18 SNAKE TL CB125F"),
            "LLANTA TRAS 90/90-18 SNAKE TL CB125F")

    # --- patrones de referencia nuevos --------------------------------
    def test_sufijo_de_lote_pegado_con_barra(self):
        self.assertEqual(
            self._nombre("342123/51 PASTILLAS MF FRENO NO ABS FZ16/PULSAR135/DISCOVER"),
            "PASTILLAS MF FRENO NO ABS FZ16/PULSAR135/DISCOVER")

    def test_honda_ferreteria_bloque_medio_5_digitos(self):
        self.assertEqual(
            self._nombre("96001-06016-00S TORNILLO FLANGE, 6X16/CB 110"),
            "TORNILLO FLANGE, 6X16/CB 110")

    def test_guion_pegado_al_nombre(self):
        self.assertEqual(
            self._nombre("50661-KRH-900-CAUCHO ESTRIBO"), "CAUCHO ESTRIBO")

    def test_referencia_pegada_a_la_primera_palabra(self):
        self.assertEqual(
            self._nombre("88110-KRH-901ESPEJO DER XR150/XR190"),
            "ESPEJO DER XR150/XR190")

    def test_referencia_incrustada_entre_parentesis(self):
        self.assertEqual(
            self._nombre("06179-K3C-E00 CABLE ACELERADOR(17910-K3C-E00) CB100"),
            "CABLE ACELERADOR CB100")

    # --- lo que ya funcionaba NO se rompe ----------------------------
    def test_no_regresion_en_casos_buenos(self):
        casos = {
            "01210-K14-910 KIT CILINDRO (CB 110) DREAN":
                ("01210-K14-910", "KIT CILINDRO (CB 110) DREAN"),
            "17211-KRH-780 FILTRO DE AIRE (CB110)":
                ("17211-KRH-780", "FILTRO DE AIRE (CB110)"),
            "20K410S KIT DE ARRASTRE PASSION":
                ("20K410S", "KIT DE ARRASTRE PASSION"),
            "08233-M99-K1LQD ACEITE HONDA 10W30":
                ("08233-M99-K1LQD", "ACEITE HONDA 10W30"),
            "93901-25080 TORNILLO":
                ("93901-25080", "TORNILLO"),
        }
        for desc, (ref, nombre) in casos.items():
            info = parsear_descripcion(desc)
            self.assertEqual(info["referencia"], ref, desc)
            self.assertEqual(info["nombre"], nombre, desc)

    def test_sufijo_de_color_honda_no_se_parte_como_palabra(self):
        # "ZAS" es sufijo de color/acabado, no una palabra pegada.
        info = parsear_descripcion("52400-KST-951ZAS AMORTIGUADOR TRAS NEGRO ECO DELUXE")
        self.assertEqual(info["referencia"], "52400-KST-951ZAS")
        self.assertEqual(info["nombre"], "AMORTIGUADOR TRAS NEGRO ECO DELUXE")


class NombreIlegibleTests(TestCase):
    """Paso 3: rotulo de respaldo en la tarjeta + cola de trabajo en el admin."""

    def test_deteccion(self):
        for malo in ["", "  ", "3345B-AAH-001S", "52400-KWP-901",
                     "K12913HF100DS", "VH10384 ALGO"]:
            self.assertTrue(nombre_es_ilegible(malo), repr(malo))
        for bueno in ["KIT CILINDRO GRIS XR150L", "TORNILLO 6 X 110",
                      "CABLE ACELERADOR CB100", "PASTILLAS FRENO"]:
            self.assertFalse(nombre_es_ilegible(bueno), repr(bueno))

    def test_nombre_publico_cae_a_marca_referencia_modelos(self):
        p = _producto(nombre="", referencia="3345B-AAH-001S", marca="Honda",
                      modelos_compatibles="CB110, CB125F", categoria="Repuestos original")
        pub = p.nombre_publico
        self.assertNotEqual(pub.strip(), "")
        self.assertNotEqual(pub.strip(), "3345B-AAH-001S")
        self.assertIn("3345B-AAH-001S", pub)   # la referencia como rotulo, no inventada
        self.assertIn("CB110", pub)

    def test_nombre_publico_respeta_nombre_bueno(self):
        p = _producto(nombre="KIT CILINDRO GRIS XR150L")
        self.assertEqual(p.nombre_publico, "KIT CILINDRO GRIS XR150L")

    def test_serializer_expone_nombre_publico(self):
        from .serializers import ProductoSerializer
        p = _producto(nombre="", referencia="52400-KWP-901", marca="Honda")
        data = ProductoSerializer(p).data
        self.assertTrue(data["nombre"])

    def test_filtro_admin_encuentra_los_ilegibles(self):
        buenos = [_producto(nombre="FILTRO DE AIRE CB110") for _ in range(3)]
        malos = [_producto(nombre="", referencia="52400-KWP-901"),
                 _producto(nombre="3345B-AAH-001S")]
        req = RequestFactory().get("/")
        f = NombreLegibleFilter(req, {"nombre_legible": ["no"]}, Producto, None)
        ids = set(f.queryset(None, Producto.objects.all()).values_list("id", flat=True))
        self.assertEqual(ids, {m.id for m in malos})

        f_ok = NombreLegibleFilter(req, {"nombre_legible": ["si"]}, Producto, None)
        ids_ok = set(f_ok.queryset(None, Producto.objects.all()).values_list("id", flat=True))
        self.assertEqual(ids_ok, {b.id for b in buenos})


class MigracionReparseoTests(TestCase):
    """0010: re-parsea los productos ya cargados y repuebla texto_busqueda."""

    def setUp(self):
        self.mig = importlib.import_module("tienda.migrations.0010_reparsear_nombres")

    def _crudo(self, **campos):
        p = _producto(**{k: v for k, v in campos.items() if k != "texto_busqueda"})
        Producto.objects.filter(pk=p.pk).update(**campos)  # .update() evita save()
        return p.pk

    def test_reparsea_y_cubre_todas_las_filas(self):
        pk_codigo = self._crudo(
            nombre="VH10384 KIT CILINDRO GRIS XR150L",
            descripcion_original="VH10384 KIT CILINDRO GRIS XR150L",
            referencia="", modelos_compatibles="", texto_busqueda="viejo")
        pk_solo_codigo = self._crudo(
            nombre="52400-KWP-901", descripcion_original="52400-KWP-901",
            referencia="", texto_busqueda="viejo")
        self._crudo(
            nombre="FILTRO DE AIRE CB110",
            descripcion_original="17211-KRH-780 FILTRO DE AIRE (CB110)",
            referencia="17211-KRH-780", texto_busqueda="viejo")

        total = Producto.objects.count()
        self.mig.reparsear(global_apps, None)

        self.assertEqual(Producto.objects.count(), total)  # no se pierde ni se crea nada

        codigo = Producto.objects.get(pk=pk_codigo)
        self.assertEqual(codigo.nombre, "KIT CILINDRO GRIS XR150L")
        self.assertEqual(codigo.referencia, "VH10384")

        solo = Producto.objects.get(pk=pk_solo_codigo)
        self.assertEqual(solo.nombre, "")
        self.assertEqual(solo.referencia, "52400-KWP-901")

        # texto_busqueda repoblado en TODAS las filas (ninguna quedo en "viejo")
        self.assertFalse(Producto.objects.filter(texto_busqueda="viejo").exists())


class ImportadorNoProductoTests(TestCase):
    """El export de Celeste trae filas que no son repuesto (IVA, fletes,
    servicios de taller). Se importan como inactivas -- nunca se descartan en
    silencio -- y no aparecen en el catálogo."""

    NO_PRODUCTO = [
        "IVA",
        "FLETE",
        "MANO DE OBRA",
        "SINCRONIZACION MOTO CB125F",
        "lubricacion guayas",
        "REVISION DE LO 1000K",
        "SERVICIO DE TORNO",
    ]
    # piezas REALES que un filtro por palabra clave ("ajuste", "sincronizacion",
    # "seguro") se llevaría por delante -- deben entrar activas.
    FALSOS_POSITIVOS = [
        "083PA-KWP-K00 KIT SINCRONIZACION (FILTRO + BUJIA)",
        "40546-K43-900 PLACA AJUSTE DE CADENA (CB 160)",
    ]

    def _xlsx(self, filas):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Código", "Categoría", "Descripcion", "Marca", "Público", "Dispo"])
        for cod, cat, desc in filas:
            ws.append([cod, cat, desc, "Honda", 10000, 1])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        return buf

    def test_no_producto_entra_inactivo_y_los_reales_activos(self):
        filas = [(f"N{i}", "Iva" if d == "IVA" else "Repuestos original", d)
                 for i, d in enumerate(self.NO_PRODUCTO)]
        filas += [(f"R{i}", "Repuestos original", d)
                  for i, d in enumerate(self.FALSOS_POSITIVOS)]
        filas.append(("OK1", "Repuestos original", "17211-KRH-780 FILTRO DE AIRE (CB110)"))

        r = importar_excel(self._xlsx(filas))
        self.assertTrue(r["ok"])
        self.assertEqual(r["no_producto"], 7)
        self.assertTrue(any("no son repuesto" in d for d in r["detalles"]),
                        "el resumen debe dejar rastro del conteo")

        for i, d in enumerate(self.NO_PRODUCTO):
            p = Producto.objects.get(codigo_celeste=f"N{i}")
            self.assertFalse(p.activo, f"{d!r} debería quedar inactivo")

        for i, d in enumerate(self.FALSOS_POSITIVOS):
            p = Producto.objects.get(codigo_celeste=f"R{i}")
            self.assertTrue(p.activo, f"{d!r} es una pieza real, debe quedar activa")

        self.assertTrue(Producto.objects.get(codigo_celeste="OK1").activo)

    def test_reimport_no_reactiva_lo_que_ana_desactivo_a_mano(self):
        filas = [("OK1", "Repuestos original", "17211-KRH-780 FILTRO DE AIRE (CB110)")]
        importar_excel(self._xlsx(filas))
        # Ana lo oculta del catálogo desde el admin
        Producto.objects.filter(codigo_celeste="OK1").update(activo=False)

        # el mismo Excel se vuelve a subir
        r = importar_excel(self._xlsx(filas))
        self.assertEqual(r["actualizados"], 1)
        self.assertFalse(Producto.objects.get(codigo_celeste="OK1").activo,
                         "el import no debe pisar la decisión manual de Ana")

    def test_no_producto_ya_desactivado_sigue_desactivado(self):
        filas = [("N0", "Iva", "IVA")]
        importar_excel(self._xlsx(filas))
        p = Producto.objects.get(codigo_celeste="N0")
        self.assertFalse(p.activo)
        # segundo import: sigue inactivo, sin drama
        r = importar_excel(self._xlsx(filas))
        self.assertEqual(r["no_producto"], 1)
        self.assertFalse(Producto.objects.get(codigo_celeste="N0").activo)
