import io
import streamlit as st
import pandas as pd
from central_compras import CentralComprasAI

st.set_page_config(
    page_title="Central de Compras AI",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Central de Compras & Licitaciones Especializadas")
st.markdown("Agentes de compras modulares con perfiles de Category Manager y análisis integral de TCO.")

api_key_secret = st.secrets.get("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    categoria_seleccionada = st.selectbox(
        "Perfil de Category Manager",
        ["Packaging", "Agrícola (Fertilizantes y Químicos)"],
        index=0,
        help="Asigna a los 4 agentes las reglas técnicas, unidades métricas y criterios de la categoría."
    )
    
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
    st.markdown(f"🎯 **Perfil Activo:**\n- Categoría: **{categoria_seleccionada}**\n- Unidad base: **{'MILLARES (MIL)' if categoria_seleccionada == 'Packaging' else 'TONELADAS (TM)'}**")

tab_demanda, tab_historico, tab_ofertas = st.tabs([
    "1. Pedidos (Demanda Agregada)", 
    "2. Histórico ERP & PPP", 
    "3. Cotizaciones (PDF / Excel / Texto)"
])

# Valores dinámicos según perfil seleccionado
if categoria_seleccionada == "Packaging":
    default_pedidos = """- Planta Virú: Requerimiento de 250 millares de Clamshell 125g ventilada y 150,000 unidades de Tapa T125 H10.
- Planta Chiclayo: Solicitud de 100 millares de Tarrina N500 H26 y 100 millares de Tapa T500 H8.
- Fundo San José: 80,000 unidades de Clamshell 125 gr chilena."""
    default_cotizaciones_texto = """PROVEEDOR EMPAQUES DEL SUR:
- Clamshell 125 gr ventilada (PET transparente): $38.50 USD por Millar. Pago 30 días.
- Tapa T125 H10: $18.20 USD por Millar. Pago 30 días.
CLÁUSULAS: Entrega en planta 5 días hábiles. Tolerancia de deformación 0.2%.

PROVEEDOR PACKAGING GLOBAL:
- Clamshell 125g chilena: $36.00 USD por Millar. Contado anticipado.
- Tarrina N500 H26: $42.00 USD por Millar. Contado anticipado.
CLÁUSULAS ADICIONALES:
* Penalidad: $200 USD por día si el camión espera más de 3 horas para la recepción en almacén.
* Vigencia: 48 horas."""
    default_hist = pd.DataFrame({
        "codigo_erp": ["PMCLA-0331", "PMLID-0021", "PMPNT-0023", "PMLID-0024"],
        "descripcion_historica": ["CLAMSHELL 125 GR CHILENA", "TAPA T125 H10", "TARRINA N500 H26", "TAPA T500 H8"],
        "volumen_historico_mil": [350.0, 200.0, 150.0, 150.0],
        "ppp_anterior_usd_mil": [39.0, 19.5, 43.5, 21.0]
    })
else:
    default_pedidos = """- Fundo El Sol: 60 bolsas de urea 46% y 1.5 toneladas de sulfato de potasio soluble.
- Parcela Norte: 40 bolsas de fosfato diamónico y 2000 kg de nitrato de amonio 33.5%."""
    default_cotizaciones_texto = """PROVEEDOR FERTILIZANTES DEL NORTE:
- Urea 46%: $460 USD/TM puesto en fundo. Pago contado.
- Sulfato de Potasio Soluble: $890 USD/TM. Contado."""
    default_hist = pd.DataFrame({
        "codigo_erp": ["FERT-001", "FERT-002", "FERT-003", "FERT-004"],
        "descripcion_historica": ["Urea Agrícola 46% N", "Sulfato de Potasio Soluble (SOP)", "Nitrato de Amonio 33.5%", "Fosfato Diamónico (DAP)"],
        "volumen_historico_tm": [150.0, 45.0, 80.0, 60.0],
        "ppp_anterior_usd_tm": [480.0, 920.0, 510.0, 680.0]
    })

with tab_demanda:
    st.subheader(f"Demanda y Requerimientos ({categoria_seleccionada})")
    col_demanda_file, col_demanda_txt = st.columns([1, 1])
    
    with col_demanda_file:
        st.markdown("**Cargar Excel de Requerimientos / MRP**")
        uploaded_demanda = st.file_uploader(
            "Cargar consolidado o pedidos en Excel (.xlsx, .xls)",
            type=["xlsx", "xls"],
            key="demanda_uploader",
            help="Sube un archivo con los requerimientos por planta, fundo o centro de costo"
        )
        if uploaded_demanda:
            st.info(f"📂 Archivo de requerimientos cargado: `{uploaded_demanda.name}`")

    with col_demanda_txt:
        st.markdown("**O ingresar pedidos en texto / WhatsApp:**")
        pedidos_input = st.text_area(
            "Requerimientos informales (se ignora si subes un archivo Excel):", 
            value=default_pedidos, 
            height=140
        )

with tab_historico:
    st.subheader("Base de Precios Promedio Ponderados (PPP)")
    col_hist_file, col_hist_info = st.columns([1, 1])
    with col_hist_file:
        uploaded_ppp = st.file_uploader(
            f"Cargar Excel de compras históricas ({categoria_seleccionada})", 
            type=["xlsx", "xls"],
            key="hist_uploader",
            help="Detecta automáticamente Material (Código) y Texto Breve (Descripción)"
        )
    with col_hist_info:
        st.caption(f"ℹ️ El sistema calcula automáticamente el PPP en **{'USD/Millar' if categoria_seleccionada == 'Packaging' else 'USD/TM'}** reconociendo códigos SAP y homologando descripciones equivalentes.")

    if uploaded_ppp is not None:
        try:
            df_historico_calculado = CentralComprasAI.calcular_ppp_desde_excel(uploaded_ppp, categoria=categoria_seleccionada)
            st.success(f"✅ Histórico de {categoria_seleccionada} procesado y PPP calculado.")
            df_historico_input = st.data_editor(df_historico_calculado, num_rows="dynamic", use_container_width=True)
        except Exception as e:
            st.warning(f"Error procesando el archivo: {e}. Mostrando tabla base:")
            df_historico_input = st.data_editor(default_hist, num_rows="dynamic", use_container_width=True)
    else:
        df_historico_input = st.data_editor(default_hist, num_rows="dynamic", use_container_width=True)

with tab_ofertas:
    st.subheader("Cotizaciones y Cláusulas Recibidas")
    col_files, col_txt = st.columns([1, 1])
    
    with col_files:
        st.markdown("**Subir Archivos (PDF o Excel con proformas)**")
        uploaded_files = st.file_uploader(
            "Carga proformas en PDF o archivos Excel (.xlsx, .xls)", 
            type=["pdf", "xlsx", "xls"], 
            accept_multiple_files=True,
            key="ofertas_uploader"
        )
        if uploaded_files:
            st.info(f"📂 {len(uploaded_files)} archivo(s) seleccionado(s).")

    with col_txt:
        st.markdown("**O ingresar proformas en texto plano:**")
        ofertas_input = st.text_area("Texto de proformas (se ignora si subes archivos):", value=default_cotizaciones_texto, height=180)

st.markdown("---")

if st.button(f"🚀 Ejecutar Licitación de {categoria_seleccionada}", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ No se encontró una Gemini API Key configurada.")
    else:
        with st.spinner(f"El {categoria_seleccionada} Category Manager está evaluando propuestas, TCO y blindaje..."):
            try:
                servicio = CentralComprasAI(api_key=api_key, categoria=categoria_seleccionada, modelo=modelo_seleccionado)
                hist_dict = df_historico_input.to_dict(orient="list")
                
                # 1. Procesamiento de Demanda (Excel o Texto)
                if uploaded_demanda is not None:
                    excel_demanda_io = io.BytesIO(uploaded_demanda.read())
                    xls_dem = pd.ExcelFile(excel_demanda_io)
                    texto_demanda_final = f"REQUERIMIENTOS DESDE ARCHIVO EXCEL ({uploaded_demanda.name}):\n"
                    for sheet in xls_dem.sheet_names:
                        df_d = pd.read_excel(xls_dem, sheet_name=sheet).dropna(how="all").dropna(axis=1, how="all")
                        if not df_d.empty:
                            texto_demanda_final += f"[Hoja: {sheet}]\n" + df_d.to_csv(index=False, sep="|") + "\n"
                else:
                    texto_demanda_final = pedidos_input

                # 2. Procesamiento de Cotizaciones (Archivos o Texto)
                lista_pdf_bytes = []
                texto_acumulado_excel = ""
                texto_ofertas_enviar = "" if uploaded_files else ofertas_input
                
                if uploaded_files:
                    for arch in uploaded_files:
                        nombre = arch.name.lower()
                        if nombre.endswith(".pdf"):
                            lista_pdf_bytes.append({
                                "nombre": arch.name,
                                "bytes": arch.read()
                            })
                        elif nombre.endswith((".xlsx", ".xls")):
                            excel_bytes = io.Bytes
