"""Set fijo de consultas para medir la calidad de tienda.busqueda.buscar()
sin depender de probar el chat a mano cada vez. Se usa para comparar
antes/después de un cambio en busqueda.py (cascada AND/OR, diccionario de
sinónimos, orden por relevancia, etc.).

Uso:
    python manage.py probar_busqueda            -> tabla legible en consola
    python manage.py probar_busqueda --json      -> una línea JSON por consulta
                                                     (para guardar y comparar
                                                     con `diff` entre corridas)
"""
import json

from django.core.management.base import BaseCommand

from tienda import busqueda

# Cubre: las 4 consultas originales de la Fase 2.1, una por cada grupo nuevo
# de SINONIMOS agregado en esa misma fase, consultas amplias de una sola
# palabra (las que expone el corte de 2.2), casos con/sin modelo de moto, y
# una por cada grupo de SINONIMOS que tiene tilde o ñ (regresión detectada
# al cerrar 2.3: _ordenar comparaba el sinónimo sin normalizar contra el
# nombre normalizado -- el bono de sinónimo nunca se activaba para esos
# términos, aunque el conteo de resultados no lo mostrara).
CONSULTAS = [
    "pastillas freno delantera cb160",   # original -- AND/OR + modelo
    "kit arrastre xr150",                # original -- agotado + modelo
    "cuanto vale una bujia",             # original -- sin modelo
    "balineras timon cb110",             # original -- fallback + diccionario
    "necesito una tapa",                 # grupo nuevo: tapa
    "el interruptor no prende",          # grupo nuevo: interruptor
    "tornillos sueltos",                 # grupo nuevo: tornillo
    "resorte para el freno",             # grupo nuevo: resorte
    "silenciador para wave",             # grupo nuevo: silenciador + modelo
    "estribo trasero cb110",             # grupo nuevo: estribo + modelo
    "lente direccional xr150",           # grupo nuevo: lente + modelo
    "piñon de arrastre cb160",           # grupo con tilde/ñ: arrastre/pinon/corona/estrella
    "aceite",                            # amplia, una palabra -- clave para 2.2
    "filtro",                            # amplia, una palabra -- clave para 2.2
    "llanta",                            # amplia, una palabra -- clave para 2.2
    "cadena para mi cb160",              # con modelo, fuera de los grupos nuevos
]


class Command(BaseCommand):
    help = "Corre un set fijo de consultas contra busqueda.buscar() para medir regresiones."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true",
                             help="Imprime una linea JSON por consulta (para diffs).")

    def handle(self, *args, **opts):
        for q in CONSULTAS:
            productos, piezas, modelos, fallback = busqueda.buscar(q, priorizar_stock=True)
            fila = {
                "consulta": q,
                "piezas": piezas,
                "modelos": modelos,
                "fallback": fallback,
                "total": len(productos),
                "con_stock": sum(1 for p in productos if p.stock > 0),
                "top5": [p.nombre for p in productos[:5]],
            }
            if opts["json"]:
                self.stdout.write(json.dumps(fila, ensure_ascii=False))
            else:
                self.stdout.write(
                    f"{fila['consulta']!r}: total={fila['total']} "
                    f"con_stock={fila['con_stock']} fallback={fila['fallback']} "
                    f"piezas={fila['piezas']} modelos={fila['modelos']}"
                )
                for n in fila["top5"]:
                    self.stdout.write(f"    - {n}")
