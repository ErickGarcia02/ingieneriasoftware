import numpy as np
import pandas as pd

FRECUENCIAS = {
    "Por hora": ("h", 24),
    "Diaria": ("D", 7),
    "Semanal": ("W-SUN", 52),
    "Mensual": ("MS", 12),
}


def preparar(datos, fecha, valor, frecuencia, operacion, dia_primero, decimal):
    originales = datos[fecha]
    if pd.api.types.is_numeric_dtype(originales):
        raise ValueError("Selecciona una columna de fechas en formato de fecha o texto, por ejemplo 2026-11-23.")
    fechas = pd.to_datetime(originales, dayfirst=dia_primero, errors="coerce", format="mixed")
    if not pd.api.types.is_datetime64_any_dtype(fechas):
        raise ValueError("Usa fechas de una misma zona horaria.")
    valores = datos[valor]
    if not pd.api.types.is_numeric_dtype(valores):
        valores = valores.astype(str).str.strip()
        if decimal == "Coma":
            valores = valores.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        else:
            valores = valores.str.replace(",", "", regex=False)
    numeros = pd.to_numeric(valores, errors="coerce").replace([np.inf, -np.inf], np.nan)
    limpios = pd.DataFrame({"fecha": fechas, "valor": numeros}).dropna()
    if limpios.empty:
        raise ValueError("No encontré filas con fecha y valor válidos. Revisa las columnas y el separador decimal.")
    if frecuencia == "h" and (limpios.fecha.max() - limpios.fecha.min()).days > 3650:
        raise ValueError("Para la vista por hora, selecciona un archivo con hasta diez años de historial.")
    grupos = limpios.set_index("fecha").sort_index().valor.resample(frecuencia)
    serie = grupos.sum(min_count=1) if operacion == "Suma" else grupos.mean()
    return serie, len(datos) - len(limpios)


def predecir(y, pasos, ciclo, modelo, positivo):
    if modelo == "Último valor":
        pred = np.repeat(y[-1], pasos)
    elif modelo == "Media reciente":
        pred = np.repeat(y[-min(len(y), ciclo, 28):].mean(), pasos)
    elif modelo == "Repetición estacional":
        pred = np.resize(y[-ciclo:], pasos)
    else:
        t = np.arange(len(y))
        pendiente, base = np.polyfit(t, y, 1)
        residuos = y - (base + pendiente * t)
        perfil = np.bincount(t % ciclo, weights=residuos) / np.bincount(t % ciclo)
        futuro = np.arange(len(y), len(y) + pasos)
        pred = base + pendiente * futuro + perfil[futuro % ciclo]
    return np.maximum(pred, 0) if positivo else pred


def pronosticar(serie, frecuencia, ciclo, horizonte, huecos, positivo):
    if len(serie) < 10 or serie.count() < 8:
        raise ValueError("Se necesitan al menos 10 períodos de historial y 8 con datos. Prueba una frecuencia más detallada.")
    completa = serie.fillna(0) if huecos == "Usar cero" else serie.ffill()
    observada = completa if huecos == "Usar cero" else serie
    y = completa.to_numpy(dtype=float)
    ancho = min(horizonte, max(1, len(y) // 6))
    cortes = [len(y) - i * ancho for i in (3, 2, 1)]
    modelos = ["Último valor", "Media reciente"]
    if cortes[0] >= 2 * ciclo:
        modelos.extend(["Repetición estacional", "Tendencia + estacionalidad"])
    filas = []
    for modelo in modelos:
        errores = []
        for corte in cortes:
            reales = observada.iloc[corte:corte + ancho].to_numpy()
            disponibles = np.isfinite(reales)
            pred = predecir(y[:corte], ancho, ciclo, modelo, positivo)
            errores.extend((reales[disponibles] - pred[disponibles]).tolist())
        if not errores:
            raise ValueError("Los períodos de validación carecen de datos observados. Revisa los huecos o cambia la frecuencia.")
        err = np.array(errores)
        filas.append((modelo, np.abs(err).mean(), np.sqrt(np.mean(err ** 2)), len(err)))
    tabla = pd.DataFrame(filas, columns=["Modelo", "MAE", "RMSE", "Puntos evaluados"]).sort_values("MAE", kind="stable")
    ganador = tabla.iloc[0]["Modelo"]
    fechas = pd.date_range(serie.index[-1], periods=horizonte + 1, freq=frecuencia)[1:]
    futuro = pd.Series(predecir(y, horizonte, ciclo, ganador, positivo), index=fechas, name="Pronóstico")
    futuro.index.name = "Fecha"
    return futuro, tabla, ancho
