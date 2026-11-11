"""Llamadas simuladas: los casos de la consigna, dichos por una voz sintética.

Los números van en palabras, como los diría una persona por teléfono: así se prueba de verdad
que el STT y el modelo los reconstruyen bien.
"""

ANA = (
    "Soy Ana Pérez. Mi teléfono es once, cinco cinco cinco cinco, cero cero cero uno. "
    "Mi DNI termina en cuatro ocho dos uno y nací el catorce de marzo de mil novecientos noventa."
)
BRUNO = (
    "Soy Bruno Díaz. Mi teléfono es once, cinco cinco cinco cinco, cero cero cero dos. "
    "El DNI termina en siete siete tres cero y nací el dos de noviembre de mil novecientos ochenta y cinco."
)
CARLA = (
    "Soy Carla Gómez. Mi teléfono es once, cinco cinco cinco cinco, cero cero cero tres. "
    "Mi DNI termina en uno uno nueve nueve y nací el veintiuno de julio de dos mil uno."
)

CALLS: dict[str, tuple[str, ...]] = {
    # El tercer mensaje existe porque el STT a veces se come un dígito del teléfono y el agente pide repetirlo.
    "factura": (
        "Hola, mi factura de octubre vino más cara. ¿Por qué?",
        ANA,
        "Perdón, te lo repito despacio: uno, uno, cinco, cinco, cinco, cinco, cero, cero, cero, uno.",
    ),
    "plan-con-deuda": (f"{BRUNO} Quiero pasarme al plan Ilimitado.", "Bueno, dale, creá el ticket."),
    "sin-senal": (f"Hola. {CARLA} No tengo señal desde ayer.", "¿Y me pueden compensar por los días sin servicio?"),
    "baja": ("Quiero dar de baja la línea, no la uso más.",),
    "cambio-de-plan": (f"{ANA} Quiero pasarme al plan Plus treinta gigas.", "Sí, confirmo el cambio."),
}
