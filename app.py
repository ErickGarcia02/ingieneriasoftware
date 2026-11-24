from io import BytesIO
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from motor import FRECUENCIAS, preparar, pronosticar

st.set_page_config(page_title="Cast · Pronósticos", page_icon="📈", layout="wide")
st.title("Cast")
st.caption("Pronósticos de series de tiempo")
ejemplo = (Path(__file__).parent / "ejemplo_tickets.csv").read_bytes()
with st.sidebar:
    st.header("Datos y pronóstico")
    fuente = st.radio("Fuente", ["Ejemplo de tickets", "Subir archivo"], horizontal=True)
    if fuente == "Ejemplo de tickets":
        datos = pd.read_csv(BytesIO(ejemplo))
        st.download_button("Descargar CSV de ejemplo", ejemplo, "ejemplo_tickets.csv", "text/csv")
    else:
        archivo = st.file_uploader("Archivo CSV o Excel", type=["csv", "xlsx"])
        if archivo is None:
            st.info("Carga un archivo con una columna de fechas y otra de valores.")
            st.stop()
        try:
            if archivo.name.lower().endswith(".xlsx"):
                libro = pd.ExcelFile(archivo, engine="openpyxl")
                datos = libro.parse(st.selectbox("Hoja de Excel", libro.sheet_names))
            else:
                contenido = archivo.getvalue()
                try:
                    contenido = contenido.decode("utf-8-sig")
                except UnicodeDecodeError:
                    contenido = contenido.decode("cp1252")
                from io import StringIO
                datos = pd.read_csv(StringIO(contenido), sep=None, engine="python")
        except Exception as error:
            st.error(f"No se pudo leer el archivo. {error}")
            st.stop()
    if len(datos.columns) < 2 or datos.empty:
        st.error("Se necesitan al menos dos columnas y una fila de datos.")
        st.stop()
    fecha = st.selectbox("Columna de fecha", datos.columns)
    opciones = [c for c in datos.columns if c != fecha]
    valor = st.selectbox("Valor a pronosticar", opciones)
    escala = st.selectbox("Frecuencia", list(FRECUENCIAS), index=1)
    frecuencia, ciclo = FRECUENCIAS[escala]
    horizonte = st.number_input("Períodos a pronosticar", 1, 365, 14)
    with st.expander("Ajustes de datos"):
        operacion = st.radio("Combinar filas de un período", ["Suma", "Promedio"], help="Suma para volúmenes. Promedio para mediciones o tasas.")
        huecos = st.selectbox("Períodos sin registros", ["Repetir último valor", "Usar cero"])
        positivo = st.checkbox("Limitar el pronóstico a valores ≥ 0", True)
        dia_primero = st.checkbox("Fechas ambiguas en orden día/mes", True)
        decimal = st.radio("Separador decimal en valores de texto", ["Punto", "Coma"], horizontal=True)
try:
    serie, omitidas = preparar(datos, fecha, valor, frecuencia, operacion, dia_primero, decimal)
    futuro, tabla, ancho = pronosticar(serie, frecuencia, ciclo, horizonte, huecos, positivo)
except (ValueError, TypeError, OverflowError) as error:
    st.warning(str(error))
    st.stop()
if omitidas or serie.isna().any():
    st.info(f"Filas omitidas por fecha o valor inválido: {omitidas}. Períodos sin registros: {serie.isna().sum()}. Tratamiento: {huecos.lower()}.")
st.subheader(f"Pronóstico de {valor}")
if fuente == "Ejemplo de tickets":
    st.caption("Datos simulados de tickets de soporte.")
ganador = tabla.iloc[0]
col1, col2, col3 = st.columns(3)
col1.metric("Próximo período", f"{futuro.iloc[0]:,.2f}")
col2.metric("Promedio proyectado", f"{futuro.mean():,.2f}")
col3.metric("Error histórico (MAE)", f"{ganador['MAE']:,.2f}")
st.caption(f"Modelo seleccionado · {ganador['Modelo']}  |  Horizonte · {horizonte} períodos")
hist = serie.rename("Valor").rename_axis("Fecha").reset_index().assign(Serie="Histórico")
proy = futuro.rename("Valor").reset_index().assign(Serie="Pronóstico")
trazo = pd.concat([hist.tail(1).assign(Serie="Pronóstico"), proy])
graf = pd.concat([hist, trazo], ignore_index=True)
# Limita la vista a los períodos recientes. Las métricas usan todo el historial.
graf = graf[graf.Fecha >= hist.Fecha.iloc[-min(len(hist), 365)]]
chart = alt.Chart(graf).mark_line(strokeWidth=2.6, point=len(graf) < 45).encode(
    x=alt.X("Fecha:T", title=None),
    y=alt.Y("Valor:Q", title=str(valor), scale=alt.Scale(zero=False)),
    color=alt.Color("Serie:N", title=None, scale=alt.Scale(domain=["Histórico","Pronóstico"], range=["#47647D","#087A67"])),
    strokeDash=alt.StrokeDash("Serie:N", legend=None, scale=alt.Scale(domain=["Histórico","Pronóstico"], range=[[1,0],[6,4]])),
    tooltip=[alt.Tooltip("Fecha:T", format="%d/%m/%Y %H:%M"), "Serie:N", alt.Tooltip("Valor:Q", format=",.2f")],
).properties(height=315).interactive()
st.altair_chart(chart, width="stretch")
if len(hist) > 365:
    st.caption("La gráfica muestra los últimos 365 períodos del historial.")
vista, validacion = st.tabs(["Pronóstico", "Comparación de modelos"])
with vista:
    salida = futuro.reset_index()
    st.download_button("Descargar pronóstico CSV", salida.to_csv(index=False).encode("utf-8-sig"), "cast_pronostico.csv", "text/csv", type="primary")
    st.dataframe(salida, hide_index=True, width="stretch")
with validacion:
    st.write(f"Cast prueba cada modelo en tres bloques consecutivos de {ancho} períodos usando solo los datos anteriores a cada bloque. Elige el modelo con el menor error absoluto medio (MAE), medido en unidades de {valor}.")
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption(f"Los modelos estacionales necesitan al menos dos ciclos de {ciclo} períodos antes del primer bloque de validación. Incluye solo períodos cerrados para evitar que un total parcial distorsione el resultado.")
