"""Formato de pesos colombianos para las plantillas del panel: mismo criterio
que fmt() en static/js/bot.js -- puntos de miles, sin decimales, sin depender
de locale (evita que el mismo número salga distinto según el navegador)."""
from django import template

register = template.Library()


@register.filter
def pesos(valor):
    try:
        n = int(round(float(valor or 0)))
    except (TypeError, ValueError):
        return "$0"
    return "$" + f"{n:,}".replace(",", ".")
