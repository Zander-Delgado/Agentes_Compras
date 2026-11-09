import io
import time
import json
import pandas as pd
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# --- Configuración de Perfiles de Category Manager ---

PERFILES_CATEGORIA = {
    "Packaging": {
        "nombre": "Category Manager de Materiales de Empaque",
        "unidad_base": "MILLAR",
        "unidad_precio": "USD/Millar",
        "criterio_tecnico": (
            "- Unidad estándar: MILLAR (1 millar = 1,000 unidades/piezas). Si cotizan en unidades/piezas, multiplica por 1000 para llegar a USD/Millar.\n"
            "- Variables técnicas críticas: Tipo de resina/material (PET, R-PET, PP, Cartón corrugado, liner), calibre/micras, gramaje (g), dimensiones (mm), cavidades y compatibilidad con tapa/fondo.\n"
            "- Homologación estricta: NO agrupar clamshells, tapas o tarrinas de gramajes, capacidades o moldes distintos (ej. 125g vs 500g, o Tapa Cubo vs Clamshell son SKUs distintos).\n"
            "- Variables logísticas y de calidad: Cajas por pallet, unidades por caja, certificación de inocuidad alimentaria (FDA/BRC), tolerancia de alabeo o deformación térmica."
        )
    },
    "Agrícola (Fertilizantes y Químicos)": {
        "nombre": "Category Manager de Nutrición y Sanidad Vegetal",
        "unidad_base": "TM",
        "unidad_precio": "USD/TM",
        "criterio_tecnico": (
            "- Unidad estándar: TM (1 TM = 1,000 kg o 20 sacos de 50 kg). Si cotizan por saco de 50 kg, multiplica por 20 para llegar a USD/TM. Para líquidos de alta densidad mantén L o peso equivalente.\n"
            "- Variables técnicas críticas: Grado NPK, porcentaje de pureza elemental (% N, % P, % K), ingrediente activo (I.A.), tipo de formulación y solubilidad.\n"
            "- Homologación estricta: NUNCA agrupar productos con concentraciones distintas (ej. Urea 46% vs Urea 40% vs Urea 15% son SKUs totalmente distintos).\n"
            "- Variables logísticas y de calidad: Tolerancia de mermas, tiempos de sobrestadía en descarga de tolvas/camiones, apelmazamiento y registro SENASA."
        )
    }
}

# --- Esquemas Pydantic Estructurados ---

class ItemDemanda(BaseModel):
    agricultor: str = Field(description="Fundo, solicitante o planta")
    fundo: str = Field(description="Ubicación o destino")
    producto_solicitado: str
    producto_estandarizado: str = Field(description="Nombre estandarizado según la categoría")
    especificacion_o_concentracion: str = Field(description="Gramaje/material/calibre en empaque, o grado/% en agrícola")
    estado_o_tipo: str = Field(description="Tipo de empaque o estado físico")
    cantidad_original: float
    unidad_original: str
    volumen_estandarizado: float = Field(description="Volumen expresado en la unidad base de la categoría")

class ListaDemanda(BaseModel):
    pedidos: List[ItemDemanda]

class ItemEstrategia(BaseModel):
    codigo_historico: str = Field(default="N/A", description="Código de artículo histórico del ERP")
    producto: str
    especificacion: str
    volumen_total: float
    ppp_historico: float
    precio_objetivo: float
    precio_techo: float
    estrategia_sourcing: str
    argumento_negociacion: str

class ListaEstrategia(BaseModel):
    estrategias: List[ItemEstrategia]

class ItemOfertaEvaluada(BaseModel):
    proveedor: str
    producto: str
    codigo_erp_mapeado: str = Field(default="N/A", description="Código del producto reconocido")
    producto_historico_relacionado: str = Field(default="", description="Descripción histórica emparejada")
    especificacion_detectada: str
    presentacion_cotizada: str
    precio_original_cotizado: str
    precio_ofertado_unidad_base: float
    precio_techo_referencia: float
    desviacion_vs_techo_pct: float
    estado_precio: str
    condiciones_pago: str
    lugar_entrega: str
    dias_entrega: int
    penalidades_y_moras: str
    restricciones_logisticas: str
    nivel_riesgo_contractual: str

class ListaOfertasEvaluadas(BaseModel):
    ofertas: List[ItemOfertaEvaluada]

class ItemAdjudicacion(BaseModel):
    producto: str
    especificacion: str
    volumen_total: float
    proveedor_ganador: str
    precio_final_unidad_base: float
    gasto_total_usd: float
    gasto_techo_usd: float
    ahorro_generado_usd: float
    riesgo_contractual: str
    justificacion_decision: str
    observaciones_contractuales_oc: str

class ComunicacionFormal(BaseModel):
    asunto: str
    cuerpo_correo: str

class ResultadoLicitacion(BaseModel):
    resumen_adjudicacion: List[ItemAdjudicacion]
    ahorro_total_consolidado_usd: float
    dictamen_riesgo_global: str
    comunicacion_formal: ComunicacionFormal


class CentralComprasAI:
    def __init__(self, api_key: str, categoria: str = "Packaging", modelo: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.modelo = modelo
        self.categoria = categoria if categoria in PERFILES_CATEGORIA else "Packaging"
        self.perfil = PERFILES_CATEGORIA[self.categoria]
        self.total_tokens_consumidos = 0

    def _invocar_gemini_schema(self, system_prompt: str, contents_input, pydantic_class, max_intentos: int = 3):
        for i in range(max_intentos):
            try:
                response = self.client.models.generate_content(
                    model=self.modelo,
                    contents=contents_input,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=pydantic_class
                    )
                )
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    self.total_tokens_consumidos += (response.usage_metadata.total_token_count or 0)
                return json.loads(response.text)
            except Exception as e:
                if "429" in str(e) or i < max_intentos - 1:
                    time.sleep(5)
                else:
                    raise e

    @staticmethod
    def calcular_ppp_desde_excel(file_bytes, categoria: str = "Packaging") -> pd.DataFrame:
        df = pd.read_excel(file_bytes)
        col_map = {c: str(c).strip().lower().replace(" ", "_") for c in df.columns}
        df = df.rename(columns=col_map)
        cols = list(df.columns)

        col_cod = None
        for pattern in ["material", "codigo", "cod", "sku", "item"]:
            found = next((c for c in cols if pattern in c and "texto" not in c and "desc" not in c), None)
            if found:
                col_cod = found
                break

        col_desc = None
        for pattern in ["texto", "desc", "denominacion", "articulo", "producto", "nombre"]:
            found = next((c for c in cols if pattern in c and c != col_cod), None)
            if found:
                col_desc = found
                break

        col_cant = next((c for c in cols if any(k in c for k in ["cant", "peso", "volumen", "qty"])), None)
        col_um = next((c for c in cols if any(k in c for k in ["und", "um", "unidad", "medida"])), None)
        col_precio = next((c for c in cols if any(k in c for k in ["precio", "costo", "unitario", "val_unit", "neto"])), None)
        col_total = next((c for c in cols if any(k in c for k in ["total", "importe", "monto", "val_tot"])), None)

        if not col_desc and not col_cod:
            raise ValueError("No se encontraron columnas de Código ni de Descripción.")

        if not col_desc:
            col_desc = col_cod
        if not col_cod:
            col_cod = col_desc

        if not col_cant or (not col_precio and not col_total):
            raise ValueError("El archivo Excel debe contener columnas de Cantidad y Precio/Total.")

        df = df.dropna(subset=[col_cant]).copy()
        df[col_cant] = pd.to_numeric(df[col_cant], errors="coerce").fillna(0)

        # Conversión de unidades adaptada al perfil
        def convertir_unidades(row):
            um = str(row[col_um]).lower() if col_um and pd.notna(row[col_um]) else ""
            cant = row[col_cant]
            if categoria == "Packaging":
                # Unidad base: Millares (1 millar = 1,000 unidades)
                if any(k in um for k in ["mil", "mill"]):
                    return cant
                elif any(k in um for k in ["und", "unid", "pza", "piez", "caj"]):
                    return cant / 1000.0
                return cant / 1000.0
            else:
                # Unidad base: TM (1 TM = 1,000 kg)
                if any(k in um for k in ["saco", "bolsa"]):
                    return (cant * 50) / 1000.0
                elif any(k in um for k in ["kg", "kilo", "litro", "l"]):
                    return cant / 1000.0
                elif any(k in um for k in ["tm", "ton"]):
                    return cant
                return cant / 1000.0

        df["volumen_estandarizado"] = df.apply(convertir_unidades, axis=1)

        # Cálculo de gasto monetario
        if col_total and col_total in df.columns:
            df["gasto_usd"] = pd.to_numeric(df[col_total], errors="coerce").fillna(0)
        else:
            df["precio_num"] = pd.to_numeric(df[col_precio], errors="coerce").fillna(0)
            def calcular_gasto(row):
                um = str(row[col_um]).lower() if col_um and pd.notna(row[col_um]) else ""
                p = row["precio_num"]
                cant = row[col_cant]
                # Si el precio ya viene expresado por millar o por TM
                if (categoria == "Packaging" and any(k in um for k in ["mil", "mill"])) or \
                   (categoria != "Packaging" and any(k in um for k in ["tm", "ton"])):
                    return row["volumen_estandarizado"] * p
                else:
                    return cant * p
            df["gasto_usd"] = df.apply(calcular_gasto, axis=1)

        group_cols = [col_cod, col_desc] if col_cod != col_desc else [col_desc]
        resumen = df.groupby(group_cols).agg(
            volumen_total_comprado=("volumen_estandarizado", "sum"),
            gasto_total_acumulado_usd=("gasto_usd", "sum")
        ).reset_index()

        resumen = resumen[resumen["volumen_total_comprado"] > 0].copy()
        resumen["ppp_anterior"] = (resumen["gasto_total_acumulado_usd"] / resumen["volumen_total_comprado"]).round(2)

        unidad_label = "volumen_historico_mil" if categoria == "Packaging" else "volumen_historico_tm"
        precio_label = "ppp_anterior_usd_mil" if categoria == "Packaging" else "ppp_anterior_usd_tm"

        resumen = resumen.rename(columns={
            col_cod: "codigo_erp",
            col_desc: "descripcion_historica",
            "volumen_total_comprado": unidad_label,
            "ppp_anterior": precio_label
        })

        return resumen[["codigo_erp", "descripcion_historica", unidad_label, precio_label]]

    def ejecutar_licitacion_completa(self, pedidos_crudos: str, data_historica: dict, cotizaciones_crudas: str = "", archivos_pdf: list = None, datos_excel: str = ""):
        if archivos_pdf is None:
            archivos_pdf = []
        self.total_tokens_consumidos = 0

        unidad_base = self.perfil["unidad_base"]
        unidad_precio = self.perfil["unidad_precio"]
        criterio = self.perfil["criterio_tecnico"]

        # 1. Agente Consolidador
        prompt_agente1 = f"""
        Eres el {self.perfil['nombre']} (Agente Consolidador).
        REGLAS DE CATEGORÍA:
        {criterio}
        Normaliza los pedidos informales. Convierte todas las cantidades a la unidad base: {unidad_base}.
        """
        pedidos_dict = self._invocar_gemini_schema(prompt_agente1, pedidos_crudos, ListaDemanda)
        df_pedidos = pd.DataFrame(pedidos_dict.get("pedidos", []))

        resumen_demanda = df_pedidos.groupby(["producto_estandarizado", "especificacion_o_concentracion", "estado_o_tipo"]).agg(
            Volumen_Total=("volumen_estandarizado", "sum"),
            Nro_Pedidos=("agricultor", "count")
        ).reset_index()

        time.sleep(1)

        # 2. Agente Estratega
        df_hist = pd.DataFrame(data_historica)
        demanda_compacta = resumen_demanda[['producto_estandarizado', 'especificacion_o_concentracion', 'Volumen_Total']].to_csv(index=False, sep="|")
        hist_compacto = df_hist.to_csv(index=False, sep="|")
        
        prompt_agente2 = f"""
        Eres el {self.perfil['nombre']} (Agente Estratega).
        REGLAS DE CATEGORÍA:
        {criterio}
        Cruza la demanda con el catálogo histórico PPP (expresado en {unidad_precio}).
        Reconoce códigos de material del ERP y sinónimos técnicos. Fija precio techo y objetivo.
        """
        ctx_estratega = f"DEMANDA ({unidad_base}):\n{demanda_compacta}\nHISTÓRICO ({unidad_precio}):\n{hist_compacto}"
        estrategia_dict = self._invocar_gemini_schema(prompt_agente2, ctx_estratega, ListaEstrategia)
        df_estrategia = pd.DataFrame(estrategia_dict.get("estrategias", []))

        time.sleep(1)

        # 3. Agente Evaluador y Auditor Legal
        techo_compacto = df_estrategia[['codigo_historico', 'producto', 'especificacion', 'precio_techo', 'precio_objetivo']].to_csv(index=False, sep="|")
        prompt_agente3 = f"""
        Eres el {self.perfil['nombre']} (Agente Evaluador Técnico-Legal).
        REGLAS DE CATEGORÍA:
        {criterio}
        Homologa todo precio cotizado a la unidad base: {unidad_precio}.
        Empareja contra el 'codigo_erp_mapeado' y evalúa admisibilidad vs precio techo.
        Audita penalidades por sobrestadía/demoras, requisitos logísticos y clasifica el riesgo contractual (BAJO, MEDIO, ALTO).
        """
        
        ctx_evaluador = [f"CATÁLOGO TECHOS ({unidad_precio}):\n{techo_compacto}"]
        if cotizaciones_crudas.strip():
            ctx_evaluador.append(f"TEXTO:\n{cotizaciones_crudas}")
        if datos_excel.strip():
            ctx_evaluador.append(f"EXCEL_OFERTAS:\n{datos_excel}")
        for pdf in archivos_pdf:
            ctx_evaluador.append(types.Part.from_bytes(data=pdf["bytes"], mime_type="application/pdf"))

        proformas_dict = self._invocar_gemini_schema(prompt_agente3, ctx_evaluador, ListaOfertasEvaluadas)
        df_proformas = pd.DataFrame(proformas_dict.get("ofertas", []))

        time.sleep(1)

        # 4. Agente Orquestador (TCO y Dictamen)
        eval_compacta = df_proformas[['proveedor', 'producto', 'especificacion_detectada', 'codigo_erp_mapeado', 'precio_ofertado_unidad_base', 'nivel_riesgo_contractual', 'penalidades_y_moras']].to_csv(index=False, sep="|")
        prompt_agente4 = f"""
        Eres el Director de Compras Globales y Riesgo Corporativo para {self.categoria}.
        Adjudica balanceando TCO, calidad técnica del material y mitigación de penalidades.
        Si la opción más económica impone penalidades o riesgos operativos desproporcionados, adjudica al siguiente postor seguro.
        Redacta las condiciones obligatorias de blindaje para la Orden de Compra.
        """
        ctx_orquestador = f"DEMANDA:\n{demanda_compacta}\nEVALUACIÓN:\n{eval_compacta}"
        resultado_adjudicacion = self._invocar_gemini_schema(prompt_agente4, ctx_orquestador, ResultadoLicitacion)

        return {
            "demanda_consolidada": resumen_demanda,
            "estrategia_precios": df_estrategia,
            "cuadro_comparativo": df_proformas,
            "adjudicacion": pd.DataFrame(resultado_adjudicacion["resumen_adjudicacion"]),
            "ahorro_total_usd": resultado_adjudicacion["ahorro_total_consolidado_usd"],
            "dictamen_riesgo": resultado_adjudicacion.get("dictamen_riesgo_global", "Evaluación completada."),
            "comunicacion_cierre": resultado_adjudicacion["comunicacion_formal"],
            "total_tokens_usados": self.total_tokens_consumidos
        }
