import streamlit as st
import pandas as pd
from central_compras import CentralComprasAI

st.set_page_config(
    page_title="Central de Compras AI",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 Central de Compras & Licitaciones Agroindustriales")
st.markdown("Automatización de compras consolidadas con agentes IA usando Google Gemini.")

with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("Gemini API Key", type="password", help="Ingresa tu API Key de Google AI Studio")
    modelo_seleccionado = st.selectbox(
        "Modelo de Gemini",
        ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"],
        index=0
    )
    st.markdown("---")
    st.markdown("💡 **Flujo:**\n1. Normaliza demanda.\n2. Aplica techos PPP.\n3. Homologa proformas.\n4. Adjudica y audita ahorros.")

tab_demanda, tab_historico, tab_ofertas = st.tabs([
    "1. Pedidos (WhatsApp / Texto)",
    "2. Precios Históricos (PPP)",
    "3. Cotizaciones de Proveedores"
])

with tab_demanda:
    st.subheader("Entrada de Demanda de Productores")
    default_pedidos = """- Don Jacinto: 60 bolsas de urea y 1.5 toneladas de sulfato de potasio soluble para Fundo El Sol.
- Ing. Roberto: requerimiento de 40 bolsas de fosfato diamónico y 2000 kg de nitrato de amonio.
- Cooperativa Norte: 10 toneladas métricas de urea 46% a granel o sacos."""
    pedidos_input = st.text_area("Requerimientos crudos:", value=default_pedidos, height=140)

with tab_historico:
    st.subheader("Base de Referencia Histórica (USD/TM)")
    default_hist = pd.DataFrame({
        "producto": ["Urea Agrícola 46% N", "Sulfato de Potasio Soluble", "Nitrato de Amonio", "Fosfato Diamónico"],
        "ppp_anterior_usd_tm": [480.0, 920.0, 510.0, 680.0],
        "tendencia_mercado": ["A la baja", "Estable", "Alza moderada", "Estable"]
    })
    df_historico_input = st.data_editor(default_hist, num_rows="dynamic", use_container_width=True)

with tab_ofertas:
    st.subheader("Cotizaciones Recibidas")
    st.caption("Nota: Más adelante esta sección admitirá subida directa de archivos PDF.")
    default_ofertas = """PROVEEDOR A (Molinos & Fertilizantes del Perú):
- Urea 46%: $22.50 USD por bolsa de 50 kg. Pago contado. Entrega en su local.
- Sulfato de Potasio: $890 USD/TM puesto en almacén. Contado.

PROVEEDOR B (Yara Distribución / Yara Perú):
- Urea 46%: $465 USD por Tonelada Métrica. Crédito 30 días. Despacho incluido.
- Nitrato de Amonio: $498 USD por Tonelada Métrica. Crédito 30 días.
- Fosfato Diamónico: $660 USD por TM. Crédito 30 días."""
    ofertas_input = st.text_area("Proformas de proveedores:", value=default_ofertas, height=160)

st.markdown("---")

if st.button("🚀 Ejecutar Pipeline de Licitación", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Por favor ingresa tu API Key de Gemini en la barra lateral izquierda.")
    else:
        with st.spinner("Los agentes están analizando y licitando la demanda..."):
            try:
                servicio = CentralComprasAI(api_key=api_key, modelo=modelo_seleccionado)
                hist_dict = df_historico_input.to_dict(orient="list")

                reporte = servicio.ejecutar_licitacion_completa(
                    pedidos_crudos=pedidos_input,
                    data_historica=hist_dict,
                    cotizaciones_crudas=ofertas_input
                )

                ahorro = reporte["ahorro_total_usd"]
                st.success("✅ Proceso completado exitosamente.")
                col_metric, _ = st.columns([1, 2])
                col_metric.metric("Ahorro Total Consolidado", f"${ahorro:,.2f} USD")

                res_tab1, res_tab2, res_tab3, res_tab4 = st.tabs([
                    "🏆 Adjudicación Final",
                    "📑 Comparativo de Proformas",
                    "📊 Estrategia de Precios",
                    "📦 Demanda Consolidada"
                ])

                with res_tab1:
                    st.dataframe(reporte["adjudicacion"], use_container_width=True)
                    st.subheader("📧 Comunicación de Adjudicación")
                    st.text_input("Asunto:", value=reporte["comunicacion_cierre"]["asunto"], disabled=True)
                    st.text_area("Cuerpo del Correo:", value=reporte["comunicacion_cierre"]["cuerpo_correo"], height=160)

                with res_tab2:
                    st.dataframe(reporte["cuadro_comparativo"], use_container_width=True)

                with res_tab3:
                    st.dataframe(reporte["estrategia_precios"], use_container_width=True)

                with res_tab4:
                    st.dataframe(reporte["demanda_consolidada"], use_container_width=True)

            except Exception as e:
                st.error(f"Error durante la ejecución del pipeline: {e}")
