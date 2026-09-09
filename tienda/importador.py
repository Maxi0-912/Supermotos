"""
Importador del Excel exportado desde Celeste MIPYME.

Columnas esperadas (según pantalla de Productos de Celeste):
  Código | PLU | Categoría | Unidad | Descripcion | Marca | Dispo | Pendiente | Cant | Público

El mapeo es FLEXIBLE: se busca cada columna por nombre (sin tildes, sin
mayúsculas) entre los encabezados reales del archivo, de modo que si el
export de Celeste trae nombres levemente distintos, basta ajustar ALIAS.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from .models import Producto, parsear_descripcion

# nombre_interno -> posibles encabezados en el Excel de Celeste
ALIAS = {
    "codigo":     ["codigo", "cod", "codigo celeste", "id"],
    "descripcion":["descripcion", "descripcion o nombre del producto", "nombre", "producto"],
    "categoria":  ["categoria", "linea"],
    "marca":      ["marca"],
    "stock":      ["dispo", "disponible", "cant", "cantidad", "existencia", "stock", "saldo"],
    "precio":     ["publico", "precio publico", "precio general", "precio", "pvp", "valor"],
}

def _normalizar(texto):
    t = str(texto or "").strip().lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _a_numero(valor):
    """Convierte '390.000', '390,000', ' $390.000 ', 390000.0 -> Decimal."""
    if valor is None or valor == "":
        return Decimal(0)
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(round(float(valor))))
    s = re.sub(r"[^\d\-,\.]", "", str(valor))
    # Formato colombiano: punto = miles, coma = decimales
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")   # 390.000 -> 390000
    elif "." in s and s.count(".") > 1:
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return Decimal(str(round(float(s))))
    except (InvalidOperation, ValueError):
        return Decimal(0)

def _a_entero(valor):
    try:
        return int(float(str(valor).replace(",", ".")))
    except (ValueError, TypeError):
        return 0


def detectar_columnas(fila_encabezados):
    """Devuelve {nombre_interno: indice_columna} buscando por alias."""
    encabezados = [_normalizar(c) for c in fila_encabezados]
    mapa = {}
    for interno, posibles in ALIAS.items():
        for i, enc in enumerate(encabezados):
            if enc and any(enc == p or p in enc for p in posibles):
                mapa[interno] = i
                break
    return mapa


def importar_excel(ruta_o_archivo, desactivar_faltantes=False):
    """Importa/actualiza productos. Devuelve dict con resumen.
    - Llave de sincronización: codigo (Código Celeste)
    - Limpia stock negativo (queda 0 para la web, se guarda el real)
    - Parsea referencia Honda y modelos desde la descripción
    """
    # NOTA: no usar read_only=True. Los export de Celeste vienen sin estilos
    # por defecto y en ese modo openpyxl reporta mal las dimensiones (1x1),
    # perdiendo todas las filas. En modo normal se leen correctas.
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = load_workbook(ruta_o_archivo, data_only=True)
    except Exception:
        # Archivo que no es un .xlsx válido (subieron un PDF, un .xls viejo,
        # un archivo corrupto). Se devuelve como error normal en vez de
        # reventar con un 500 en el panel.
        return {"ok": False, "error": "No se pudo abrir el archivo. Debe ser el "
                "Excel (.xlsx) exportado desde Productos en Celeste.",
                "creados": 0, "actualizados": 0, "omitidos": 0, "detalles": []}
    hoja = wb.active

    # Cargar todas las filas a memoria (3 mil filas es trivial)
    todas = [[c.value for c in fila] for fila in hoja.iter_rows()]

    # Buscar la fila de encabezados (puede no ser la primera)
    mapa, fila_datos_inicio = None, 0
    for idx, fila in enumerate(todas[:12]):
        posible = detectar_columnas(fila)
        if "codigo" in posible and "descripcion" in posible:
            mapa = posible
            fila_datos_inicio = idx + 1
            break

    if not mapa:
        return {"ok": False, "error": "No se encontraron las columnas Código y Descripción en el archivo. Revisa que sea el Excel exportado desde Productos en Celeste.", "creados": 0, "actualizados": 0, "omitidos": 0, "detalles": []}

    creados = actualizados = omitidos = 0
    detalles = []
    codigos_vistos = set()

    for idx, fila in enumerate(todas):
        if idx < fila_datos_inicio:
            continue
        try:
            codigo_raw = fila[mapa["codigo"]]
            descripcion = str(fila[mapa["descripcion"]] or "").strip()
            # El código puede venir como float (2593.0), int o texto ("2.593")
            if isinstance(codigo_raw, float):
                codigo = str(int(codigo_raw))
            elif isinstance(codigo_raw, int):
                codigo = str(codigo_raw)
            else:
                codigo = str(codigo_raw or "").strip()
                # Texto tipo "2.593" (punto de miles) -> "2593"
                if re.fullmatch(r"[\d.,]+", codigo):
                    codigo = codigo.replace(".", "").replace(",", "")
            if not codigo or not descripcion:
                omitidos += 1
                continue
            if codigo in codigos_vistos:
                detalles.append(f"Fila {idx+1}: código duplicado {codigo}, se usó la última aparición.")
            codigos_vistos.add(codigo)

            info = parsear_descripcion(descripcion)
            datos = {
                "referencia": info["referencia"][:40],
                "nombre": info["nombre"][:250].strip().upper(),
                "descripcion_original": descripcion[:300],
                "modelos_compatibles": ", ".join(info["modelos"])[:250],
            }
            if "categoria" in mapa:
                datos["categoria"] = str(fila[mapa["categoria"]] or "").strip()[:100]
            if "marca" in mapa:
                marca = str(fila[mapa["marca"]] or "").strip()
                datos["marca"] = (marca if marca and _normalizar(marca) != "sin marca" else "Honda")[:60]
            if "precio" in mapa:
                datos["precio"] = _a_numero(fila[mapa["precio"]])
            if "stock" in mapa:
                datos["stock"] = _a_entero(fila[mapa["stock"]])

            _, creado = Producto.objects.update_or_create(
                codigo_celeste=codigo, defaults=datos)
            creados += int(creado)
            actualizados += int(not creado)
        except Exception as e:  # noqa: BLE001 — registrar y seguir
            omitidos += 1
            detalles.append(f"Fila {idx+1}: {e}")

    if desactivar_faltantes and codigos_vistos:
        Producto.objects.exclude(codigo_celeste__in=codigos_vistos).update(activo=False)

    return {"ok": True, "creados": creados, "actualizados": actualizados,
            "omitidos": omitidos, "detalles": detalles[:50]}
