import io
import streamlit as st
import pandas as pd
from central_compras import CentralComprasAI

st.set_page_config(
    page_title="Central de Compras AI",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 Central de Compras & Licitaciones Agroindustriales")
st.markdown("Plataforma de compras consolidadas con homologación semántica de insumos, cálculo de PPP y auditoría de TCO.")

api_key_secret = st.secrets.get("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ Configuración")
    if api_key_secret:
        api_key = api_key_secret
        st.success("🔒 Conexión segura con Gemini activa")
    else:
        api_key = st.text_input("Gemini API Key", type="password", help="Ingresa tu clave de Google AI Studio")
    
    modelo_seleccionado = st.selectbox(
        "Modelo de Gemini",
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.8-flash"],
        index=0
    )
    st.markdown("---")
    st.markdown("💡 **Capacidades Activas:**\n- Ingesta de Histórico Excel y cálculo PPP\n- Homologación de sinónimos y códigos ERP\n- Auditoría de Penalidades y TCO\n- Optimización en Tokens")

tab_demanda, tab_historico, tab_ofertas = st.tabs([
    "1. Pedidos (WhatsApp / Texto)", 
    "2. Precios Históricos (PPP / Excel)", 
    "3. Cotizaciones (PDF / Excel / Texto)"
])

with tab_demanda:
    st.subheader("Entrada de Demanda de Productores")
    default_pedidos = """- Don Jacinto: 60 bolsas de urea y 1.5 toneladas de sulfato de potasio soluble para Fundo El Sol.
- Ing. Roberto: requerimiento de 40 bolsas de fosfato diamónico y 2000 kg de nitrato de amonio.
- Cooperativa Norte: 10 toneladas métricas de urea 46% a granel o sacos."""
    pedidos_input = st.text_area("Requerimientos crudos:", value=default_pedidos, height=140)

with tab_historico:
    st.subheader("Base de Precios Promedio Ponderados (PPP)")
    
    col_hist_file, col_hist_info = st.columns([1, 1])
    with col_hist_file:
        uploaded_ppp = st.file_uploader(
            "Cargar Excel de compras históricas del ERP (.xlsx)", 
            type=["xlsx", "xls"],
            help="Sube un archivo con columnas: Código, Producto/Descripción, Cantidad, Unidad y Precio/Total"
        )
    
    with col_hist_info:
        st.caption("ℹ️ El sistema calcula automáticamente el PPP en **USD/TM** ponderando volúmenes de compras pasadas y permite reconocer sinónimos comerciales en las proformas de proveedores.")

    # Si el usuario sube su archivo histórico, calculamos el PPP con Pandas
    if uploaded_ppp is not None:
        try:
            df_historico_calculado = CentralComprasAI.calcular_ppp_desde_excel(uploaded_ppp)
            st.success("✅ Histórico procesado y PPP calculado exitosamente.")
            df_historico_input = st.data_editor(df_historico_calculado, num_rows="dynamic", use_container_width=True)
        except Exception as e:
            st.warning(f"No se pudo estructurar automáticamente el archivo: {e}. Mostrando tabla estándar:")
            default_hist = pd.DataFrame({
                "codigo_erp": ["FERT-001", "FERT-002", "FERT-003", "FERT-004"],
                "descripcion_historica": ["Urea Agrícola 46% N", "Sulfato de Potasio Soluble (SOP)", "Nitrato de Amonio Agrícola", "Fosfato Diamónico (DAP)"],
                "volumen_historico_tm": [150.0, 45.0, 80.0, 60.0],
                "ppp_anterior_usd_tm": [480.0, 920.0, 510.0, 680.0]
            })
            df_historico_input = st.data_editor(default_hist, num_rows="dynamic", use_container_width=True)
    else:
        # Tabla por defecto si no sube archivo
        default_hist = pd.DataFrame({
            "codigo_erp": ["FERT-001", "FERT-002", "FERT-003", "FERT-004"],
            "descripcion_historica": ["Urea Agrícola 46% N", "Sulfato de Potasio Soluble (SOP)", "Nitrato de Amonio Agrícola", "Fosfato Diamónico (DAP)"],
            "volumen_historico_tm": [150.0, 45.0, 80.0, 60.0],
            "ppp_anterior_usd_tm": [480.0, 920.0, 510.0, 680.0]
        })
        df_historico_input = st.data_editor(default_hist, num_rows="dynamic", use_container_width=True)

with tab_ofertas:
    st.subheader("Cotizaciones y Cláusulas Recibidas")
    col_files, col_txt = st.columns([1, 1])
    
    with col_files:
        st.markdown("**Subir Archivos (PDF o Excel con proformas)**")
        uploaded_files = st.file_uploader(
            "Carga proformas en PDF o archivos Excel (.xlsx, .xls)", 
            type=["pdf", "xlsx", "xls"], 
            accept_multiple_files=True
        )
        if uploaded_files:
            st.info(f"📂 {len(uploaded_files)} archivo(s) seleccionado(s).")

    with col_txt:
        st.markdown("**O pegar cotizaciones y términos en texto:**")
        default_ofertas = """PROVEEDOR A (Molinos & Fertilizantes del Perú):
- Urea perlada 46% granulada: $458 USD/TM puesto en almacén. Pago contado anticipado.
- Muriato / Sulfato Potásico soluble: $890 USD/TM puesto en almacén. Contado.
CLÁUSULAS ADICIONALES:
* Penalidad: Cobro de $150 USD por día de sobrestadía si el camión espera más de 2 horas para descargar en fundo.
* Tolerancia de merma: Máximo 0.5% reconocida por el proveedor.
* Vigencia: 48 horas calendario.

PROVEEDOR B (Yara Distribución / Yara Perú):
- Urea agrícola estándar: $465 USD por Tonelada Métrica. Crédito 30 días. Despacho incluido.
- Nitrato amónico: $498 USD por Tonelada Métrica. Crédito 30 días.
- Fosfato diamónico 18-46-0 (DAP): $660 USD por TM. Crédito 30 días.
CLÁUSULAS ADICIONALES:
* Logística: Entrega en tolvas o bolsas de 50kg en 4 días hábiles.
* Penalidades: Sin cobro por tiempos de espera de descarga razonables (hasta 6 horas).
* Vigencia: 15 días calendario."""
        ofertas_input = st.text_area("Texto de proformas y términos:", value=default_ofertas, height=180)

st.markdown("---")

if st.button("🚀 Ejecutar Pipeline de Licitación con Análisis TCO & PPP", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ No se encontró una Gemini API Key configurada.")
    else:
        with st.spinner("Homologando sinónimos contra el histórico, auditando penalidades y calculando TCO..."):
            try:
                servicio = CentralComprasAI(api_key=api_key, modelo=modelo_seleccionado)
                hist_dict = df_historico_input.to_dict(orient="list")
                
                lista_pdf_bytes = []
                texto_acumulado_excel = ""
                
                if uploaded_files:
                    for arch in uploaded_files:
                        nombre = arch.name.lower()
                        if nombre.endswith(".pdf"):
                            lista_pdf_bytes.append({
                                "nombre": arch.name,
                                "bytes": arch.read()
                            })
                        elif nombre.endswith((".xlsx", ".xls")):
                            excel_bytes = io.BytesIO(arch.read())
                            xls = pd.ExcelFile(excel_bytes)
                            for sheet_name in xls.sheet_names:
                                df_sheet = pd.read_excel(xls, sheet_name=sheet_name)
                                df_sheet = df_sheet.dropna(how="all").dropna(axis=1, how="all")
                                if not df_sheet.empty:
                                    texto_acumulado_excel += f"[Hoja:{sheet_name}]\n"
                                    texto_acumulado_excel += df_sheet.to_csv(index=False, sep="|") + "\n"

                reporte = servicio.ejecutar_licitacion_completa(
                    pedidos_crudos=pedidos_input,
                    data_historica=hist_dict,
                    cotizaciones_crudas=ofertas_input,
                    archivos_pdf=lista_pdf_bytes,
                    datos_excel=texto_acumulado_excel
                )
                
                ahorro = reporte["ahorro_total_usd"]
                tokens_usados = reporte.get("total_tokens_usados", 0)
                st.success("✅ Licitación, homologación de catálogo y análisis de riesgos completados.")
                
                col_metric, col_tokens, col_riesgo = st.columns([1, 1, 2])
                col_metric.metric("Ahorro Total Consolidado", f"${ahorro:,.2f} USD")
                col_tokens.metric("Tokens Consumidos", f"{tokens_usados:,}")
                col_riesgo.info(f"🛡️ **Dictamen de Riesgo Global:**\n{reporte['dictamen_riesgo']}")

                res_tab1, res_tab2, res_tab3, res_tab4 = st.tabs([
                    "🏆 Adjudicación y Blindaje O.C.",
                    "📑 Matriz de Proformas y Homologación ERP",
                    "📊 Estrategia de Precios Techo vs PPP",
                    "📦 Demanda Consolidada"
                ])
                
                with res_tab1:
                    st.dataframe(reporte["adjudicacion"], use_container_width=True)
                    st.subheader("📧 Comunicación de Adjudicación y Condiciones")
                    st.text_input("Asunto:", value=reporte["comunicacion_cierre"]["asunto"], disabled=True)
                    st.text_area("Cuerpo del Correo / O.C.:", value=reporte["comunicacion_cierre"]["cuerpo_correo"], height=180)

                with res_tab2:
                    st.dataframe(reporte["cuadro_comparativo"], use_container_width=True)

                with res_tab3:
                    st.dataframe(reporte["estrategia_precios"], use_container_width=True)

                with res_tab4:
                    st.dataframe(reporte["demanda_consolidada"], use_container_width=True)

            except Exception as e:
                st.error(f"Error durante la ejecución del pipeline: {e}")
