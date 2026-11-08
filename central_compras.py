import time
import json
import pandas as pd
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# --- Esquemas Pydantic para minimizar tokens de salida y prompt ---

class ItemDemanda(BaseModel):
    agricultor: str = Field(description="Nombre del productor o fundo")
    fundo: str = Field(description="Ubicación o fundo")
    producto_solicitado: str
    producto_estandarizado: str
    cantidad_original: float
    unidad_original: str
    volumen_total_kg: float

class ItemEstrategia(BaseModel):
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

        # 2. Agente Estratega (Datos compactos con delimitador pipe)
        df_hist = pd.DataFrame(data_historica)
        demanda_compacta = resumen_demanda[['producto_estandarizado', 'Volumen_Total_TM']].to_csv(index=False, sep="|")
        hist_compacto = df_hist.to_csv(index=False, sep="|")
        
        prompt_agente2 = "Estratega Sourcing: con demanda e histórico PPP (USD/TM), fija techo, precio objetivo y argumento de negociación por volumen."
        ctx_estratega = f"DEMANDA:\n{demanda_compacta}\nHISTÓRICO:\n{hist_compacto}"
        estrategia_json = self._invocar_gemini_schema(prompt_agente2, ctx_estratega, List[ItemEstrategia])
        df_estrategia = pd.DataFrame(estrategia_json)

        time.sleep(1)

        # 3. Agente Evaluador y Auditor Legal
        techo_compacto = df_estrategia[['producto', 'precio_techo_usd_tm', 'precio_objetivo_usd_tm']].to_csv(index=False, sep="|")
        prompt_agente3 = (
            "Evaluador Técnico-Legal: homologa precios a USD/TM (saco 50kg * 20), evalúa admisibilidad vs precio techo, "
            "audita penalidades/moras, restricciones logísticas y asigna nivel_riesgo_contractual (BAJO, MEDIO, ALTO)."
        )
        
        ctx_evaluador = [f"TECHOS:\n{techo_compacto}"]
        if cotizaciones_crudas.strip():
            ctx_evaluador.append(f"TEXTO:\n{cotizaciones_crudas}")
        if datos_excel.strip():
            ctx_evaluador.append(f"EXCEL:\n{datos_excel}")
        for pdf in archivos_pdf:
            ctx_evaluador.append(types.Part.from_bytes(data=pdf["bytes"], mime_type="application/pdf"))

        proformas_json = self._invocar_gemini_schema(prompt_agente3, ctx_evaluador, List[ItemOfertaEvaluada])
        df_proformas = pd.DataFrame(proformas_json)

        time.sleep(1)

        # 4. Agente Orquestador (TCO y Dictamen)
        eval_compacta = df_proformas[['proveedor', 'producto', 'precio_ofertado_usd_tm', 'nivel_riesgo_contractual', 'penalidades_y_moras']].to_csv(index=False, sep="|")
        prompt_agente4 = (
            "Director Compras TCO: adjudica minimizando costo total y riesgo operativo/legal. "
            "Si el menor precio tiene riesgo ALTO por penalidades, adjudica al siguiente mejor postor. Redacta blindaje para OC."
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
