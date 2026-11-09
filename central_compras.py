import io
import time
import json
import pandas as pd
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# --- Esquemas Pydantic Estructurados ---

class ItemDemanda(BaseModel):
    agricultor: str = Field(description="Nombre del productor o fundo")
    fundo: str = Field(description="Ubicación o fundo")
    producto_solicitado: str
    producto_estandarizado: str
    cantidad_original: float
    unidad_original: str
    volumen_total_kg: float

class ItemEstrategia(BaseModel):
    codigo_historico: Optional[str] = Field(default="N/A", description="Código de artículo histórico del ERP si coincide")
    producto: str
    volumen_tm: float
    ppp_historico_usd_tm: float
    precio_objetivo_usd_tm: float
    precio_techo_usd_tm: float
    estrategia_sourcing: str
    argumento_negociacion: str

class ItemOfertaEvaluada(BaseModel):
    proveedor: str
    producto: str
    codigo_erp_mapeado: Optional[str] = Field(default="N/A", description="Código del producto histórico reconocido")
    producto_historico_relacionado: Optional[str] = Field(default="", description="Nombre con el que figuraba en el histórico")
    presentacion_cotizada: str
    precio_original_cotizado: str
    precio_ofertado_usd_tm: float
    precio_techo_referencia_usd_tm: float
    desviacion_vs_techo_pct: float = Field(alias="desviacion_vs_techo_%")
    estado_precio: str
    condiciones_pago: str
    lugar_entrega: str
    dias_entrega: int
    penalidades_y_moras: str
    restricciones_logisticas: str
    nivel_riesgo_contractual: str

class ItemAdjudicacion(BaseModel):
    producto: str
    volumen_tm: float
    proveedor_ganador: str
    precio_final_usd_tm: float
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
    def __init__(self, api_key: str, modelo: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.modelo = modelo
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
    def calcular_ppp_desde_excel(file_bytes) -> pd.DataFrame:
        """
        Lee el Excel histórico de compras y calcula el PPP exacto ponderado por volumen en TM.
        Busca columnas típicas: código, descripción/producto, cantidad, unidad y precio unitario o total.
        """
        df = pd.read_excel(file_bytes)
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        # Mapeo flexible de nombres de columnas
        col_cod = next((c for c in df.columns if any(k in c for k in ["cod", "sku", "item"])), None)
        col_desc = next((c for c in df.columns if any(k in c for k in ["desc", "prod", "articulo", "material"])), None)
        col_cant = next((c for c in df.columns if any(k in c for k in ["cant", "peso", "volumen", "qty"])), None)
        col_um = next((c for c in df.columns if any(k in c for k in ["und", "um", "unidad", "medida"])), None)
        col_precio = next((c for c in df.columns if any(k in c for k in ["precio", "costo", "unitario", "val_unit"])), None)
        col_total = next((c for c in df.columns if any(k in c for k in ["total", "importe", "monto"])), None)

        if not col_desc or (not col_precio and not col_total) or not col_cant:
            raise ValueError("El archivo Excel debe contener al menos columnas de Descripción/Producto, Cantidad y Precio/Total.")

        # Limpieza de nulos
        df = df.dropna(subset=[col_desc, col_cant]).copy()
        df[col_cant] = pd.to_numeric(df[col_cant], errors="coerce").fillna(0)

        # Conversión a Toneladas Métricas (TM) según unidad
        def convertir_a_tm(row):
            um = str(row[col_um]).lower() if col_um and pd.notna(row[col_um]) else "kg"
            cant = row[col_cant]
            if "saco" in um or "bolsa" in um:
                return (cant * 50) / 1000.0
            elif "kg" in um or "kilo" in um:
                return cant / 1000.0
            elif "tm" in um or "ton" in um:
                return cant
            return cant / 1000.0

        df["volumen_tm"] = df.apply(convertir_a_tm, axis=1)

        # Cálculo del gasto total por compra
        if col_total and col_total in df.columns:
            df["gasto_usd"] = pd.to_numeric(df[col_total], errors="coerce").fillna(0)
        else:
            df["precio_num"] = pd.to_numeric(df[col_precio], errors="coerce").fillna(0)
            def calcular_gasto(row):
                um = str(row[col_um]).lower() if col_um and pd.notna(row[col_um]) else "kg"
                p = row["precio_num"]
                cant = row[col_cant]
                # Si el precio unitario era por saco de 50kg o por kg
                if "tm" in um or "ton" in um:
                    return row["volumen_tm"] * p
                elif "saco" in um or "bolsa" in um:
                    return cant * p
                else: # asume kg
                    return cant * p
            df["gasto_usd"] = df.apply(calcular_gasto, axis=1)

        # Agrupación y cálculo del Precio Promedio Ponderado (PPP)
        group_cols = [col_desc]
        if col_cod:
            group_cols.insert(0, col_cod)

        resumen = df.groupby(group_cols).agg(
            volumen_total_comprado_tm=("volumen_tm", "sum"),
            gasto_total_acumulado_usd=("gasto_usd", "sum")
        ).reset_index()

        # Evitar división por cero
        resumen = resumen[resumen["volumen_total_comprado_tm"] > 0].copy()
        resumen["ppp_historico_usd_tm"] = (resumen["gasto_total_acumulado_usd"] / resumen["volumen_total_comprado_tm"]).round(2)

        # Renombrar columnas estandarizadas
        nombres_finales = {
            col_desc: "descripcion_historica",
            "volumen_total_comprado_tm": "volumen_historico_tm",
            "ppp_historico_usd_tm": "ppp_anterior_usd_tm"
        }
        if col_cod:
            nombres_finales[col_cod] = "codigo_erp"
        else:
            resumen["codigo_erp"] = "SIN-COD"

        resumen = resumen.rename(columns=nombres_finales)
        return resumen[["codigo_erp", "descripcion_historica", "volumen_historico_tm", "ppp_anterior_usd_tm"]]

    def ejecutar_licitacion_completa(self, pedidos_crudos: str, data_historica: dict, cotizaciones_crudas: str = "", archivos_pdf: list = None, datos_excel: str = ""):
        if archivos_pdf is None:
            archivos_pdf = []
        self.total_tokens_consumidos = 0

        # 1. Agente Consolidador
        prompt_agente1 = "Consolidador Agro: normaliza pedidos informales, estandariza fertilizantes comerciales y calcula volumen_total_kg (1 saco=50kg, 1TM=1000kg)."
        pedidos_json = self._invocar_gemini_schema(prompt_agente1, pedidos_crudos, List[ItemDemanda])
        df_pedidos = pd.DataFrame(pedidos_json)

        resumen_demanda = df_pedidos.groupby("producto_estandarizado").agg(
            Volumen_Total_KG=("volumen_total_kg", "sum"),
            Nro_Pedidos=("agricultor", "count")
        ).reset_index()
        resumen_demanda["Volumen_Total_TM"] = resumen_demanda["Volumen_Total_KG"] / 1000

        time.sleep(1)

        # 2. Agente Estratega (Cruza con Histórico PPP)
        df_hist = pd.DataFrame(data_historica)
        demanda_compacta = resumen_demanda[['producto_estandarizado', 'Volumen_Total_TM']].to_csv(index=False, sep="|")
        hist_compacto = df_hist.to_csv(index=False, sep="|")
        
        prompt_agente2 = (
            "Estratega Sourcing: cruza la demanda con el histórico PPP (USD/TM). Reconoce sinónimos o nombres similares. "
            "Asocia el codigo_historico correspondiente del ERP. Fija precio techo (máximo admisible) y precio objetivo por volumen."
        )
        ctx_estratega = f"DEMANDA:\n{demanda_compacta}\nHISTÓRICO_CON_PPP:\n{hist_compacto}"
        estrategia_json = self._invocar_gemini_schema(prompt_agente2, ctx_estratega, List[ItemEstrategia])
        df_estrategia = pd.DataFrame(estrategia_json)

        time.sleep(1)

        # 3. Agente Evaluador y Auditor Legal (Mapea sinónimos de proformas contra histórico)
        techo_compacto = df_estrategia[['codigo_historico', 'producto', 'precio_techo_usd_tm', 'precio_objetivo_usd_tm']].to_csv(index=False, sep="|")
        prompt_agente3 = (
            "Evaluador Técnico-Legal: homologa precios de proformas a USD/TM (saco 50kg * 20). "
            "Reconoce sinónimos o marcas comerciales y mapea al 'codigo_erp_mapeado' y 'producto_historico_relacionado'. "
            "Evalúa si el precio es ADMISIBLE vs techo, audita penalidades/moras, logística y asigna nivel_riesgo_contractual (BAJO, MEDIO, ALTO)."
        )
        
        ctx_evaluador = [f"CATALOGO_HISTORICO_Y_TECHOS:\n{techo_compacto}"]
        if cotizaciones_crudas.strip():
            ctx_evaluador.append(f"TEXTO:\n{cotizaciones_crudas}")
        if datos_excel.strip():
            ctx_evaluador.append(f"EXCEL_PROFORMAS:\n{datos_excel}")
        for pdf in archivos_pdf:
            ctx_evaluador.append(types.Part.from_bytes(data=pdf["bytes"], mime_type="application/pdf"))

        proformas_json = self._invocar_gemini_schema(prompt_agente3, ctx_evaluador, List[ItemOfertaEvaluada])
        df_proformas = pd.DataFrame(proformas_json)

        time.sleep(1)

        # 4. Agente Orquestador (TCO y Dictamen)
        eval_compacta = df_proformas[['proveedor', 'producto', 'codigo_erp_mapeado', 'precio_ofertado_usd_tm', 'nivel_riesgo_contractual', 'penalidades_y_moras']].to_csv(index=False, sep="|")
        prompt_agente4 = (
            "Director Compras TCO: adjudica balanceando menor costo total y mitigación de riesgo. "
            "Si la oferta más económica tiene riesgo ALTO por penalidades, adjudica al siguiente postor y documenta el blindaje de la OC."
        )
        ctx_orquestador = f"DEMANDA:\n{demanda_compacta}\nEVALUACION:\n{eval_compacta}"
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
