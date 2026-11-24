from csv import Error as ErrorCSV
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from motor import AUTO, CONTEO, HORIZONTES, MODELOS, agrupar, limpiar, pronosticar

st.set_page_config(page_title="Cast · Demanda", page_icon="📈", layout="wide")
AREAS = ["Operaciones", "Ventas", "Servicio al Cliente", "Finanzas"]
PAGINAS = ["Dashboard", "Fuentes y conjuntos de datos", "Pipeline y calidad", "Modelos y pronósticos", "Historial"]
EJEMPLO = (Path(__file__).parent / "ejemplo_tickets.csv").read_bytes()
HUECOS = ["Repetir último valor", "Usar cero"]


def ahora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def registrar(area, tipo, nombre, estado, detalle):
    area["eventos"].insert(0, dict(Fecha=ahora(), Proceso=tipo, Conjunto=nombre, Estado=estado, Detalle=detalle))


def guardar_datos(area, nombre, fuente, serie, errores, validas, total, promedio, huecos, unidad):
    anterior = area["datasets"].get(nombre)
    version = anterior["version"] + 1 if anterior else 1
    datos = dict(nombre=nombre, fuente=fuente, serie=serie, errores=errores, validas=validas, total=total,
                 promedio=promedio, huecos=huecos, unidad=unidad, version=version)
    area["datasets"][nombre] = datos
    registrar(area, "Importación", nombre, "Completada", f"v{version} · {validas}/{total} filas válidas · {fuente}")
    return datos


def ejecutar(area, datos, h, modelo):
    resultado = pronosticar(datos["serie"], h, modelo, datos["huecos"])
    resultado.update(id=uuid4().hex[:8], fecha=ahora(), dataset=datos["nombre"], version=datos["version"],
                     horizonte=h, seleccion=modelo, corte=datos["serie"].index[-1], promedio=datos["promedio"])
    area["runs"].insert(0, resultado)
    registrar(area, "Pronóstico", datos["nombre"], "Completado", f"{resultado['modelo']} · {h} días · {resultado['id']}")
    return resultado


def estado_inicial():
    areas = {nombre: {"datasets": {}, "eventos": [], "runs": []} for nombre in AREAS}
    demo = pd.read_csv(BytesIO(EJEMPLO))
    serie, errores, validas = limpiar(demo, "Fecha", "Tickets", True, "Punto", True)
    op = areas["Operaciones"]
    datos = guardar_datos(op, "Tickets de ejemplo", "CSV simulado", serie, errores, validas, len(demo), False, HUECOS[0], "Tickets")
    ejecutar(op, datos, 14, AUTO)
    return areas


def csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def grafica(lineas, titulo_y):
    fig = go.Figure()
    for nombre, serie, color, estilo in lineas:
        fig.add_scatter(x=serie.index, y=serie, name=nombre, mode="lines+markers" if len(serie) <= 30 else "lines",
                        line=dict(color=color, width=2.6, dash=estilo), marker=dict(size=5),
                        hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.2f}<extra>%{fullData.name}</extra>")
    fig.update_layout(height=355, margin=dict(l=10, r=12, t=10, b=16), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.14), yaxis_title=titulo_y)
    return fig


def vista_datos(area, espacio):
    st.subheader("Fuentes y conjuntos de datos")
    if area["datasets"]:
        st.dataframe(pd.DataFrame([{"Conjunto": d["nombre"], "Fuente": d["fuente"], "Versión": d["version"],
                                    "Filas válidas": d["validas"]} for d in area["datasets"].values()]),
                     hide_index=True, width="stretch")
    st.download_button("Descargar plantilla CSV", EJEMPLO, "plantilla_cast.csv", "text/csv")
    archivo = st.file_uploader("Subir archivo local", type=["csv", "xlsx"], key=f"archivo-{espacio}")
    if archivo is None:
        st.caption("Carga un historial con fecha y volumen, o un registro por ticket, lead o pedido.")
        return
    try:
        if archivo.name.lower().endswith(".xlsx"):
            libro = pd.ExcelFile(BytesIO(archivo.getvalue()), engine="openpyxl")
            hoja = st.selectbox("Hoja de Excel", libro.sheet_names)
            frame = libro.parse(hoja)
        else:
            contenido = archivo.getvalue()
            try:
                texto = contenido.decode("utf-8-sig")
            except UnicodeDecodeError:
                texto = contenido.decode("cp1252")
            sep = st.selectbox("Separador del CSV", ["Automático", "Coma", "Punto y coma", "Tabulación"])
            seps = {"Automático": None, "Coma": ",", "Punto y coma": ";", "Tabulación": "\t"}
            if sep == "Automático" and all(c not in texto.splitlines()[0] for c in [",", ";", "\t", "|"]):
                frame = pd.read_csv(StringIO(texto), sep=",")
            else:
                frame = pd.read_csv(StringIO(texto), sep=seps[sep], engine="python")
        if frame.empty:
            raise ValueError("El archivo está vacío.")
    except (ValueError, OSError, KeyError, IndexError, BadZipFile, ErrorCSV) as e:
        st.error(f"No se pudo leer el archivo. {e}")
        return
    frame.columns = frame.columns.astype(str)
    with st.expander(f"Vista previa · {len(frame):,} filas", expanded=True):
        st.dataframe(frame.head(8), hide_index=True, width="stretch")
    nombre = st.text_input("Nombre del conjunto", value=Path(archivo.name).stem, key=f"nombre-{espacio}-{archivo.file_id}").strip()
    if nombre in area["datasets"]:
        st.info("La importación guardará una nueva versión. Incluye el historial completo y los resultados reales nuevos.")
    cols = st.columns(2)
    fecha = cols[0].selectbox("Columna de fecha", frame.columns)
    otras = [c for c in frame.columns if c != fecha]
    valor = cols[1].selectbox("Volumen", otras + [CONTEO])
    with st.expander("Formato y reglas de limpieza"):
        orden = st.checkbox("Interpretar fechas ambiguas como día/mes", True)
        decimal = st.radio("Separador decimal", ["Punto", "Coma"], horizontal=True)
        operacion = st.radio("Combinar valores del mismo día", ["Suma", "Promedio"], horizontal=True, disabled=valor == CONTEO)
        huecos = st.selectbox("Días sin registros para el pronóstico", HUECOS)
        st.caption("Las filas con fecha inválida o volumen negativo o vacío quedan en el reporte de calidad. Varias filas del mismo día pueden representar eventos distintos.")
    if st.button("Importar conjunto", type="primary", disabled=not nombre):
        try:
            serie, errores, validas = limpiar(frame, fecha, valor, orden, decimal, operacion == "Suma")
            if not validas:
                st.dataframe(errores.head(100), hide_index=True)
                raise ValueError("Ninguna fila tiene fecha y volumen válidos.")
            guardar_datos(area, nombre, archivo.name, serie, errores, validas, len(frame),
                          operacion == "Promedio" and valor != CONTEO, huecos, "Eventos" if valor == CONTEO else valor)
            st.session_state[f"activar-{espacio}"] = nombre
            st.session_state[f"aviso-{espacio}"] = f"{nombre} importado. Abre Modelos y pronósticos para generar su proyección."
            st.rerun()
        except (ValueError, OverflowError) as e:
            registrar(area, "Importación", nombre, "Fallida", str(e))
            st.error(str(e))


def calidad(datos):
    st.subheader("Pipeline y calidad de datos")
    a, b, c, d = st.columns(4)
    a.metric("Filas recibidas", datos["total"])
    b.metric("Filas válidas", datos["validas"])
    c.metric("Filas excluidas", len(datos["errores"]))
    d.metric("Días sin registros", int(datos["serie"].isna().sum()))
    st.caption(f"{datos['fuente']} · Versión {datos['version']} · Tratamiento de días vacíos: {datos['huecos'].lower()}.")
    if not datos["errores"].empty:
        st.markdown("**Registros excluidos**")
        st.dataframe(datos["errores"], hide_index=True, width="stretch")
        st.download_button("Descargar incidencias", csv(datos["errores"]), "cast_incidencias.csv")
    st.markdown("**Historial procesado**")
    st.dataframe(datos["serie"].reset_index(), hide_index=True, width="stretch")
    st.download_button("Descargar historial limpio", csv(datos["serie"].reset_index()), "cast_historico.csv")


def modelos(area, datos, espacio, vigente):
    st.subheader("Modelos y pronósticos")
    ident = (espacio, datos["nombre"])
    pref = st.session_state.setdefault("preferencias", {}).get(ident, (14, AUTO))
    a, b = st.columns([1, 2])
    h = a.selectbox("Horizonte en días", HORIZONTES, index=HORIZONTES.index(pref[0]), key=f"h-{ident}")
    modelo = b.selectbox("Modelo", [AUTO] + MODELOS, index=([AUTO] + MODELOS).index(pref[1]), key=f"m-{ident}")
    if st.button("Generar pronóstico", type="primary"):
        try:
            vigente = ejecutar(area, datos, h, modelo)
            st.session_state["preferencias"][ident] = (h, modelo)
            st.success(f"Pronóstico guardado en esta sesión · {vigente['id']}")
        except ValueError as e:
            registrar(area, "Pronóstico", datos["nombre"], "Fallido", str(e))
            st.error(str(e))
    if vigente:
        st.caption(f"Resultado guardado · {vigente['modelo']} · {vigente['horizonte']} días · {vigente['fecha']}")
        st.dataframe(vigente["metricas"], hide_index=True, width="stretch")
        st.caption(f"Validación con tres bloques consecutivos de {vigente['ancho']} días. MAE se expresa en unidades de volumen. WAPE es el error absoluto total dividido entre el volumen real total y queda vacío si ese volumen es cero.")
        if vigente["fallos"]:
            st.warning("Modelos sin ajuste válido: " + ", ".join(vigente["fallos"]))
        val = vigente["validacion"].set_index("Fecha")
        st.markdown("**Validación histórica del modelo elegido**")
        st.plotly_chart(grafica([("Real", val.Real, "#314E6B", "solid"), ("Pronóstico", val["Pronóstico"], "#00806B", "dash")], datos["unidad"]), width="stretch")
        resultados(vigente)


def resultados(run):
    st.dataframe(run["futuro"].reset_index(), hide_index=True, width="stretch")
    st.caption("Los límites son una referencia empírica basada en el percentil 90 del error absoluto de validación.")
    st.download_button("Descargar pronóstico CSV", csv(run["futuro"].reset_index()), f"cast_{run['id']}.csv", "text/csv")


def dashboard(datos, run):
    st.subheader(datos["nombre"])
    semanal = st.radio("Vista del dashboard", ["Diaria", "Semanal"], horizontal=True) == "Semanal"
    hist = agrupar(datos["serie"], semanal, datos["promedio"])
    a, b, c = st.columns(3)
    a.metric("Último día observado", f"{datos['serie'].dropna().iloc[-1]:,.2f}")
    b.metric("Días con datos", f"{datos['serie'].count():,}")
    c.metric("Demanda prevista" if not datos["promedio"] else "Promedio previsto",
             (f"{(run['futuro']['Pronóstico'].mean() if datos['promedio'] else run['futuro']['Pronóstico'].sum()):,.1f}" if run else "Pendiente"))
    if run:
        st.caption(f"{run['modelo']} · Próximos {run['horizonte']} días · Corte {run['corte']:%d/%m/%Y}")
    else:
        st.info("Abre Modelos y pronósticos para generar el primer resultado de esta versión.")
    lineas = [("Histórico", hist, "#314E6B", "solid")]
    if run:
        proy = agrupar(run["futuro"]["Pronóstico"], semanal, datos["promedio"])
        lineas.append(("Pronóstico", proy, "#00806B", "dash"))
    st.plotly_chart(grafica(lineas, datos["unidad"]), width="stretch")
    if semanal:
        st.caption("Semana de lunes a domingo. Histórico y pronóstico se agrupan por separado e incluyen solo los días que corresponden a cada tramo.")
    if run:
        with st.expander("Ver valores del pronóstico"):
            resultados(run)


def historial(area):
    st.subheader("Historial de ejecuciones")
    filtro = st.selectbox("Mostrar ejecuciones de", ["Todo el departamento"] + list(area["datasets"]))
    eventos = [e for e in area["eventos"] if filtro == "Todo el departamento" or e["Conjunto"] == filtro]
    if not eventos:
        st.info("Todavía no hay ejecuciones en este departamento.")
        return
    st.dataframe(pd.DataFrame(eventos), hide_index=True, width="stretch")
    runs = [r for r in area["runs"] if filtro == "Todo el departamento" or r["dataset"] == filtro]
    if not runs:
        return
    por_id = {r["id"]: r for r in runs}
    etiquetas = {r["id"]: f"{r['dataset']} · v{r['version']} · {r['modelo']} · {r['horizonte']} días · {r['id']}" for r in runs}
    elegido = st.selectbox("Consultar un pronóstico guardado", list(por_id), format_func=etiquetas.get)
    run = por_id[elegido]
    real = area["datasets"][run["dataset"]]["serie"]
    comp = run["futuro"][["Pronóstico"]].join(real.rename("Real")).dropna()
    if comp.empty:
        st.info("Para comparar contra resultados reales, importa el historial actualizado bajo el mismo nombre de conjunto.")
    else:
        error = (comp.Real - comp["Pronóstico"]).abs()
        total = comp.Real.abs().sum()
        st.markdown("**Pronóstico guardado frente a los resultados reales**")
        a, b, c = st.columns(3)
        a.metric("Días comparables", len(comp))
        b.metric("MAE observado", f"{error.mean():,.2f}")
        c.metric("WAPE observado", f"{100 * error.sum() / total:.1f} %" if total else "Sin volumen")
        st.dataframe(comp.reset_index(), hide_index=True, width="stretch")
    resultados(run)


if "cast_local_areas" not in st.session_state:
    st.session_state.cast_local_areas = estado_inicial()
with st.sidebar:
    st.title("Cast")
    espacio = st.selectbox("Espacio de trabajo", AREAS)
    area = st.session_state.cast_local_areas[espacio]
    ds_key = f"conjunto-{espacio}"
    activar = st.session_state.pop(f"activar-{espacio}", None)
    if activar:
        st.session_state[ds_key] = activar
    nombres = list(area["datasets"])
    nombre = st.selectbox("Conjunto activo", nombres, key=ds_key, placeholder="Carga un archivo", disabled=not nombres)
    pagina = st.radio("Navegación", PAGINAS)
    st.caption("Archivos e historial disponibles durante esta sesión.")
st.caption(f"CAST  /  {espacio.upper()}")
if aviso := st.session_state.pop(f"aviso-{espacio}", None):
    st.success(aviso)
datos = area["datasets"].get(nombre)
if pagina == PAGINAS[1]:
    vista_datos(area, espacio)
elif pagina == PAGINAS[4]:
    historial(area)
elif datos is None:
    st.subheader(pagina)
    st.info("Este espacio está vacío. En Fuentes y conjuntos de datos puedes importar tu primer CSV o Excel.")
else:
    vigente = next((r for r in area["runs"] if r["dataset"] == nombre and r["version"] == datos["version"]), None)
    if pagina == PAGINAS[0]:
        dashboard(datos, vigente)
    elif pagina == PAGINAS[2]:
        calidad(datos)
    else:
        modelos(area, datos, espacio, vigente)
