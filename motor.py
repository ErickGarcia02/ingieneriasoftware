import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import Holt

AUTO = "Automático · menor MAE"
CONTEO = "Contar una unidad por fila"
MODELOS = ["Último valor", "Media móvil (7 días)", "Mismo día de la semana", "Holt · tendencia amortiguada"]
HORIZONTES = [7, 14, 30, 90, 120]


def limpiar(datos, fecha, valor, orden, decimal, suma):
    columna = datos[fecha]
    if pd.api.types.is_numeric_dtype(columna):
        raise ValueError("Elige una columna con fechas de calendario o fechas de Excel.")
    # Los archivos deben usar un solo calendario; conservar la fecha local del evento.
    fechas = pd.to_datetime(columna, format="mixed", dayfirst=orden, errors="coerce")
    if not pd.api.types.is_datetime64_any_dtype(fechas):
        raise ValueError("Unifica la zona horaria de la columna de fechas.")
    fechas = fechas.dt.tz_localize(None).dt.normalize()
    if valor == CONTEO:
        numeros = pd.Series(1.0, index=datos.index)
    else:
        numeros = datos[valor]
        if not pd.api.types.is_numeric_dtype(numeros):
            numeros = numeros.astype("string").str.strip()
            miles, dec = (".", ",") if decimal == "Coma" else (",", ".")
            numeros = numeros.str.replace(miles, "", regex=False).str.replace(dec, ".", regex=False)
        numeros = pd.to_numeric(numeros, errors="coerce").astype("float64")
    mal_fecha = fechas.isna()
    mal_valor = ~np.isfinite(numeros) | (numeros < 0)
    buenas = ~(mal_fecha | mal_valor)
    motivos = np.select([mal_fecha & mal_valor, mal_fecha, mal_valor],
                        ["Fecha y volumen inválidos", "Fecha inválida", "Volumen inválido o negativo"], default="")
    errores = pd.DataFrame({"Registro": np.arange(1, len(datos) + 1), "Motivo": motivos})[~buenas.to_numpy()]
    validas = pd.DataFrame({"Fecha": fechas[buenas], "Volumen": numeros[buenas]})
    if validas.empty:
        serie = pd.Series(dtype=float, name="Volumen", index=pd.DatetimeIndex([], name="Fecha"))
    else:
        if (validas.Fecha.max() - validas.Fecha.min()).days > 36525:
            raise ValueError("El historial supera 100 años. Revisa el formato de las fechas.")
        grupos = validas.groupby("Fecha").Volumen
        serie = (grupos.sum() if suma or valor == CONTEO else grupos.mean()).asfreq("D")
    return serie, errores, int(buenas.sum())


def estimar(y, n, modelo):
    if modelo == MODELOS[0]:
        pred = np.full(n, y[-1])
    elif modelo == MODELOS[1]:
        pred = np.full(n, np.mean(y[-7:]))
    elif modelo == MODELOS[2]:
        pred = np.resize(y[-7:], n)
    elif modelo == MODELOS[3]:
        if np.ptp(y) == 0:
            pred = np.full(n, y[-1])
        else:
            ajuste = Holt(y, damped_trend=True, initialization_method="estimated").fit()
            pred = ajuste.forecast(n)
    else:
        raise ValueError("Modelo desconocido.")
    if not np.isfinite(pred).all():
        raise ValueError("El modelo produjo valores fuera del rango numérico.")
    return np.maximum(0, pred)


def pronosticar(serie, horizonte, modelo, huecos):
    if horizonte not in HORIZONTES:
        raise ValueError("Selecciona un horizonte disponible.")
    if len(serie) < 14 or serie.count() < 10:
        raise ValueError("Para pronosticar se necesitan 14 días de historial y al menos 10 días con datos.")
    cero = huecos == "Usar cero"
    y = (serie.fillna(0) if cero else serie.ffill()).to_numpy(dtype=float)
    observada = y if cero else serie.to_numpy(dtype=float)
    ancho = max(1, min(horizonte, len(y) // 6))
    cortes = [len(y) - i * ancho for i in (3, 2, 1)]
    fechas_val = serie.index[cortes[0]:]
    metricas, detalles, candidatos, fallos = [], {}, {}, []
    for nombre in MODELOS:
        try:
            validacion = np.concatenate([estimar(y[:c], ancho, nombre) for c in cortes])
            estimados = estimar(y, horizonte, nombre)
        except (ValueError, ArithmeticError, np.linalg.LinAlgError):
            fallos.append(nombre)
            continue
        reales = observada[cortes[0]:]
        mask = np.isfinite(reales)
        if not mask.any():
            raise ValueError("No hay observaciones en los tres bloques de validación. Revisa los días vacíos.")
        residuos = reales[mask] - validacion[mask]
        err = np.abs(residuos)
        volumen = np.abs(reales[mask]).sum()
        metricas.append({"Modelo": nombre, "MAE": err.mean(), "WAPE (%)": 100 * err.sum() / volumen if volumen else np.nan,
                         "RMSE": np.sqrt(np.mean(residuos ** 2)), "Días evaluados": int(mask.sum())})
        detalles[nombre] = pd.DataFrame({"Fecha": fechas_val[mask], "Real": reales[mask], "Pronóstico": validacion[mask]})
        radio = np.quantile(err, 0.90)
        candidatos[nombre] = pd.DataFrame({"Pronóstico": estimados, "Inferior": np.maximum(0, estimados - radio),
                                           "Superior": estimados + radio},
                                          index=pd.date_range(serie.index[-1] + pd.Timedelta(days=1), periods=horizonte, name="Fecha"))
    if not metricas:
        raise ValueError("No se pudo ajustar ningún modelo al historial.")
    tabla = pd.DataFrame(metricas).sort_values("MAE", kind="stable").reset_index(drop=True)
    ganador = tabla.Modelo.iloc[0] if modelo == AUTO else modelo
    if ganador not in candidatos:
        raise ValueError("El modelo seleccionado no pudo ajustarse. Prueba la selección automática.")
    return dict(modelo=ganador, futuro=candidatos[ganador], metricas=tabla, validacion=detalles[ganador],
                ancho=ancho, fallos=fallos)


def agrupar(frame, semanal, promedio=False):
    if not semanal:
        return frame
    grupos = frame.resample("W-MON", label="left", closed="left")
    return grupos.mean() if promedio else grupos.sum(min_count=1)
