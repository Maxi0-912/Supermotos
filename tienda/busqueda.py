"""Motor de búsqueda conversacional para el bot y la página."""
import re
import unicodedata
from django.db.models import Q

VACIAS = {"de","la","el","los","las","para","con","y","o","del","un","una",
    "unos","unas","mi","moto","repuesto","repuestos","quiero","necesito",
    "busco","buscar","tienes","tiene","hay","por","favor","me","algo","sobre",
    "que","cual","cuanto","cuánto","vale","valen","cuesta","precio","dame",
    "regale","ver","es"}

SINONIMOS = {
    "delantero":["del","delant","dl","delantera","front"],
    "delantera":["del","delant","dl","delantero"],
    "trasero":["tras","tra","trasera","post","tr"],
    "trasera":["tras","tra","trasero","post"],
    "pastillas":["pastilla","past","pasta"], "pastilla":["pastillas","past"],
    "bujia":["bujias","buji"],
    "amortiguador":["amortiguadores","amort","amortig"],
    "rodamiento":["rodamientos","balinera","balineras","ruliman","balin"],
    "balinera":["rodamiento","rodamientos","ruliman","balin"],
    "ruliman":["rodamiento","balinera"],
    "empaque":["empaques","emp","junta","juntas"],
    "arrastre":["sprocket","pinon","kit arrastre","transmision"],
    "cadena":["cadenas","cad","cadenilla"],
    "guaya":["guayas","cable","cables"], "cable":["guaya","guayas","cables"],
    "farola":["farol","faro","luz","optica"],
    "direccional":["direccionales","stop","intermitente","cocuyo"],
    "espejo":["espejos","retrovisor","retrovisores"], "filtro":["filtros"],
    "aceite":["lubricante","aceites","lubricantes"],
    "lubricante":["aceite","lubricantes"],
    "bateria":["baterias","pila","pilas","acumulador"],
    "pila":["bateria","baterias"],
    "llanta":["llantas","neumatico","neumaticos","rin","caucho"],
    "caucho":["llanta","llantas","neumatico"],
    "kit":["juego","conjunto","jgo"], "juego":["kit","jgo","conjunto"],
    "disco":["discos"], "freno":["frenos"],
    "frenos":["freno","pastillas","banda","bandas"],
    "manigueta":["maneta","manija","palanca"],
    "cilindro":["cilindros","kit cilindro"], "piston":["pistones"],
    "carburador":["carburadores","carbu"],
    "clutch":["croche","embrague","clotch"],
    "embrague":["clutch","croche","embrag"], "croche":["clutch","embrague"],
    "corona":["sprocket","piñon","catalina"],
    "reten":["retenedor","sello","retenes"],
    "sello":["reten","retenedor","sellos"],
    "guardabarro":["guardabarros","guardafango","salpicadera"],
    "tanque":["tanques","deposito"], "manubrio":["manillar","timon","direccion"],
    "estrella":["sprocket","piñon","arrastre"],
    "banda":["bandas","zapata","zapatas"], "valvula":["valvulas","valv"],
    "arbol":["arboles","leva","levas","camshaft"], "biela":["bielas"],
    "cabezote":["culata","cabeza"],
}

MODELOS = ["CB160F","CB160","CB190R","CB190","CB125F","CB125","CB110","CB100",
    "CBF150","CBF125","CBF160","XR150L","XR150","XR190L","XR190","XRE190",
    "XRE300","X-BLADE","XBLADE","INVICTA","NAVI","DIO","DREAM NEO","DREAM",
    "DREAN NEO","DREAN","BIZ","ELITE","WAVE","ECO DELUXE","ECO","SPLENDOR",
    "AK125","AK","BOXER","PULSAR","DISCOVER","PLATINO","GN125","APACHE","FZ",
    "GIXXER","TTR","NKD","CG125","TORNADO","CBR","HUNK","CB150"]

def normalizar(texto):
    t = str(texto or "").lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

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

def buscar(consulta, solo_stock=True, limite=40):
    from .models import Producto
    qs = Producto.objects.filter(activo=True)
    modelos = detectar_modelos(consulta)
    piezas = tokenizar_piezas(consulta, modelos)
    for termino in piezas:
        variantes = [termino] + SINONIMOS.get(termino, [])
        if termino.endswith("s") and len(termino) > 3: variantes.append(termino[:-1])
        sub = Q()
        for v in variantes: sub |= Q(nombre__icontains=v) | Q(categoria__icontains=v)
        qs = qs.filter(sub)
    if modelos:
        sub = Q()
        for m in modelos:
            vs = {m, m.replace(" ",""), m.replace("-",""), re.sub(r"([A-Za-z]+)(\d)", r"\1 \2", m)}
            for v in vs: sub |= Q(nombre__icontains=v) | Q(modelos_compatibles__icontains=v)
        qs = qs.filter(sub)
    productos = _ordenar(list(qs[:150]), piezas, modelos)
    if solo_stock:
        productos = [p for p in productos if p.stock > 0] + [p for p in productos if p.stock <= 0]
    return productos[:limite], piezas, modelos

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
        if p.stock > 0: s += 40
        return s - len(n)//100
    return sorted(productos, key=punt, reverse=True)
