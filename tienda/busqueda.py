"""Motor de búsqueda conversacional para el bot y la página."""
import logging
import re
import unicodedata
from django.db.models import Q

logger = logging.getLogger(__name__)

VACIAS = {"de","la","el","los","las","para","con","y","o","del","un","una",
    "unos","unas","mi","moto","repuesto","repuestos","quiero","necesito",
    "busco","buscar","tienes","tiene","hay","por","favor","me","algo","sobre",
    "que","cual","cuanto","cuánto","vale","valen","cuesta","precio","dame",
    "regale","ver","es"}

def normalizar(texto):
    t = str(texto or "").lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

# Grupos de equivalencia: todos los términos de un mismo grupo son sinónimos
# entre sí. Reemplaza al diccionario SINONIMOS escrito a mano (que solo tenía
# la mitad de las flechas: "manubrio" apuntaba a "timon" pero "timon" no
# apuntaba a nada, así que un cliente que escribía "timon" nunca encontraba
# el MANUBRIO del catálogo). Migrado 1 a 1 desde el diccionario anterior por
# componentes conexos, sin quitar ningún término.
# Para agregar una palabra nueva: métela en el grupo que le corresponda: ya
# queda conectada con todo lo demás del grupo, en los dos sentidos, sola.
GRUPOS_SINONIMOS = [
    ["delantero","delantera","del","delant","dl","front"],
    ["trasero","trasera","tras","tra","post","tr"],
    ["freno","frenos","pastilla","pastillas","past","pasta","banda","bandas","zapata","zapatas"],
    ["arrastre","sprocket","pinon","piñon","kit arrastre","transmision","corona","catalina","estrella"],
    ["clutch","embrague","croche","clotch","embrag"],
    ["reten","retenedor","sello","retenes","sellos"],
    ["rodamiento","rodamientos","balinera","balineras","ruliman","balin"],
    ["guaya","guayas","cable","cables"],
    ["farola","farol","faro","luz","optica"],
    ["direccional","direccionales","stop","intermitente","cocuyo"],
    ["espejo","espejos","retrovisor","retrovisores"],
    ["filtro","filtros"],
    ["aceite","lubricante","aceites","lubricantes"],
    ["bateria","baterias","pila","pilas","acumulador"],
    ["llanta","llantas","neumatico","neumaticos","rin","caucho","rueda","ruedas"],
    ["kit","juego","conjunto","jgo"],
    ["disco","discos"],
    ["empaque","empaques","emp","junta","juntas"],
    ["cadena","cadenas","cad","cadenilla"],
    ["amortiguador","amortiguadores","amort","amortig"],
    ["bujia","bujias","buji"],
    ["manigueta","maneta","manija","palanca"],
    ["cilindro","cilindros","kit cilindro"],
    ["piston","pistones"],
    ["carburador","carburadores","carbu"],
    ["guardabarro","guardabarros","guardafango","salpicadera"],
    ["tanque","tanques","deposito"],
    ["manubrio","manillar","timon","direccion"],
    ["valvula","valvulas","valv"],
    ["arbol","arboles","leva","levas","camshaft"],
    ["biela","bielas"],
    ["cabezote","culata","cabeza"],
    # Agregados a partir del escaneo del catálogo real (2.1/2.2): términos
    # frecuentes en los nombres de Celeste que no tenían ninguna entrada
    # coloquial todavía.
    ["tapa","tapas","tapon","tapones"],
    ["interruptor","suiche","pulsador"],
    ["tornillo","tornillos","perno","pernos","esparrago"],
    ["resorte","resortes","muelle","muelles"],
    ["silenciador","mofle","escape","exosto"],
    ["estribo","estribos","posapies","pisadera"],
    ["lente","lentes","mica","micas"],
]

# Se normaliza cada término ACÁ, una sola vez al construir el diccionario --
# no en cada punto donde se usa SINONIMOS -- para que una entrada con tilde o
# ñ ("piñon", "rulimán") quede indexada bajo su forma sin acentos y siga
# coincidiendo con Producto.texto_busqueda (que se guarda normalizado) y con
# _ordenar (que compara contra nombres ya normalizados). Cualquier grupo que
# se agregue a futuro con tildes queda cubierto automáticamente, sin tener
# que acordarse de normalizarlo a mano.
def _construir_sinonimos(grupos):
    d = {}
    for grupo in grupos:
        grupo_norm = list(dict.fromkeys(normalizar(t) for t in grupo))
        for termino in grupo_norm:
            d[termino] = [t for t in grupo_norm if t != termino]
    return d

SINONIMOS = _construir_sinonimos(GRUPOS_SINONIMOS)

# Ninguno de estos modelos tiene tilde/ñ hoy, pero detectar_modelos() y
# _filtrar_modelo() ya normalizan cada variante antes de compararla/buscarla
# (ver abajo), así que un modelo futuro con acento quedaría cubierto igual.
MODELOS = ["CB160F","CB160","CB190R","CB190","CB125F","CB125","CB110","CB100",
    "CBF150","CBF125","CBF160","XR150L","XR150","XR190L","XR190","XRE190",
    "XRE300","X-BLADE","XBLADE","INVICTA","NAVI","DIO","DREAM NEO","DREAM",
    "DREAN NEO","DREAN","BIZ","ELITE","WAVE","ECO DELUXE","ECO","SPLENDOR",
    "AK125","AK","BOXER","PULSAR","DISCOVER","PLATINO","GN125","APACHE","FZ",
    "GIXXER","TTR","NKD","CG125","TORNADO","CBR","HUNK","CB150"]

def detectar_modelos(consulta):
    txt = normalizar(consulta).replace("-","").replace(" ","")
    enc = []
    for m in MODELOS:
        clave = normalizar(m).replace("-","").replace(" ","")
        if clave in txt: enc.append(m)
    final = []
    for m in enc:
        mc = normalizar(m).replace(" ","").replace("-","")
        if not any(mc != normalizar(o).replace(" ","").replace("-","") and mc in normalizar(o).replace(" ","").replace("-","") for o in enc):
            final.append(m)
    return final

def tokenizar_piezas(consulta, modelos):
    txt = normalizar(consulta)
    for m in modelos: txt = txt.replace(normalizar(m)," ")
    out = []
    for p in re.split(r"[\s,;/]+", txt):
        p = p.strip("-.")
        if p and p not in VACIAS and len(p) >= 3 and not re.match(r"^(cb|xr|xre|cbf|ak|cg)$", p):
            if p not in out: out.append(p)
    return out[:6]

def _variantes(termino):
    vs = [termino] + SINONIMOS.get(termino, [])
    if termino.endswith("s") and len(termino) > 3: vs.append(termino[:-1])
    return vs

def _filtrar_modelo(qs, modelos):
    if not modelos: return qs
    sub = Q()
    for m in modelos:
        vs = {m, m.replace(" ",""), m.replace("-",""), re.sub(r"([A-Za-z]+)(\d)", r"\1 \2", m)}
        for v in vs: sub |= Q(texto_busqueda__icontains=normalizar(v))
    return qs.filter(sub)

# Cuántas filas trae la consulta SQL antes de que _ordenar puntúe por
# relevancia. Antes se cortaba en 150 en orden alfabético (Meta.ordering),
# así que con una búsqueda amplia ("llanta": 163 coincidencias reales, medido
# en el catálogo de 3.088 productos de ago-2026) el mejor resultado podía
# quedar fuera sin haber sido evaluado nunca. Ordenar por stock primero
# garantiza que, si toca cortar, se corta del lado de los agotados -- el
# mismo criterio que ya usa _ordenar vía BONUS_STOCK -- sin reimplementar
# todo su puntaje en SQL. 300 da margen frente al peor caso medido (163),
# pero es un colchón, no una garantía: si se llega a este límite, _recortar
# deja un warning en el log (ver abajo) para enterarnos antes de que un
# producto empiece a desaparecer en silencio.
CORTE_SQL = 300

# Bonus de _ordenar para un producto con stock > 0 (ver _ordenar más abajo):
# el factor más grande del puntaje después del prefijo exacto (100), a
# propósito, para que un producto disponible le gane a uno agotado salvo que
# el agotado matchee mucho mejor el texto buscado.
BONUS_STOCK = 40

def _recortar(qs, consulta):
    resultado = list(qs.order_by("-stock", "nombre")[:CORTE_SQL])
    if len(resultado) == CORTE_SQL:
        logger.warning(
            "busqueda.buscar: la consulta %r llego al corte de %s resultados; "
            "puede haber productos relevantes que nunca se evaluaron. Si esto "
            "se repite seguido, subir CORTE_SQL en tienda/busqueda.py.",
            consulta, CORTE_SQL,
        )
    return resultado

def buscar(consulta, con_stock=False, priorizar_stock=True, limite=40):
    # con_stock: filtra de verdad -- excluye los agotados del resultado.
    # priorizar_stock: NO filtra, solo reordena (los agotados quedan al
    # final) para que el bot pueda ofrecer "avísenme cuando llegue" en vez
    # de decir que el producto no existe. Antes un solo parámetro
    # (`solo_stock`) hacía una cosa acá y otra distinta en la rama de
    # catálogo/chips de ProductoViewSet -- "funcionaba por accidente"
    # porque el frontend siempre mandaba con_stock=1 dependiendo de que acá
    # NO filtrara.
    # Se filtra contra Producto.texto_busqueda (un solo TextField indexado,
    # poblado en Producto.save() con referencia+nombre+modelos_compatibles+
    # categoria ya normalizado) en vez de encadenar Q(nombre__icontains=..)
    # | Q(categoria__icontains=..) | ... por cada variante: una sola columna
    # que revisar por fila, y de paso ahora también matchea por referencia
    # Honda (antes no se buscaba ahí).
    from .models import Producto
    base = Producto.objects.filter(activo=True)
    modelos = detectar_modelos(consulta)
    piezas = tokenizar_piezas(consulta, modelos)

    # Paso 1: igual que siempre -- cada pieza debe aparecer (AND en cascada).
    qs = base
    for termino in piezas:
        sub = Q()
        for v in _variantes(termino): sub |= Q(texto_busqueda__icontains=normalizar(v))
        qs = qs.filter(sub)
    productos = _recortar(_filtrar_modelo(qs, modelos), consulta)
    uso_fallback = False

    # Paso 2: si el AND no encontró nada (habiendo piezas que buscar), se
    # reintenta con OR -- que aparezca CUALQUIERA de las piezas -- y se deja
    # que _ordenar priorice por relevancia. El modelo de moto NO se relaja
    # acá: si el cliente nombró su moto, un resultado de otra moto es peor
    # que ninguno, así que el filtro de modelo se vuelve a aplicar igual.
    if not productos and piezas:
        sub = Q()
        for termino in piezas:
            for v in _variantes(termino): sub |= Q(texto_busqueda__icontains=normalizar(v))
        productos = _recortar(_filtrar_modelo(base.filter(sub), modelos), consulta)
        uso_fallback = bool(productos)

    productos = _ordenar(productos, piezas, modelos)
    if con_stock:
        productos = [p for p in productos if p.stock > 0]
    elif priorizar_stock:
        productos = [p for p in productos if p.stock > 0] + [p for p in productos if p.stock <= 0]
    return productos[:limite], piezas, modelos, uso_fallback

def _ordenar(productos, piezas, modelos):
    def punt(p):
        n = normalizar(p.nombre); mods = normalizar(p.modelos_compatibles); s = 0
        if piezas and n.startswith(piezas[0]): s += 100
        for t in piezas:
            if t in n: s += 25
            for syn in SINONIMOS.get(t, []):
                if syn in n: s += 8
        for m in modelos:
            mm = normalizar(m)
            if mm in mods: s += 20
            if mm in n: s += 12
        if p.stock > 0: s += BONUS_STOCK
        return s - len(n)//100
    return sorted(productos, key=punt, reverse=True)
