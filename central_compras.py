import io
import time
import json
import pandas as pd
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# --- Modelos Pydantic Estrictos ---

class ItemDemanda(BaseModel):
    agricultor: str = Field(description="Nombre del productor o fundo")
    fundo: str = Field(description="Ubicación o fundo")
    producto_solicitado: str
    producto_estandarizado: str = Field(description="Nombre estandarizado incluyendo concentración química o especificación técnica")
    concentracion_o_grado: str = Field(description="Grado NPK, % o especificación de empaque/material")
    estado_fisico: str = Field(description="solido, liquido o unidad")
    cantidad_original: float
    unidad_original: str
    volumen_total_kg: float

class ListaDemanda(BaseModel):
    pedidos: List[ItemDemanda]

class ItemEstrategia(BaseModel):
    codigo_historico: str = Field(default="N/A", description="Código de artículo histórico del ERP")
    producto: str
    concentracion: str
    volumen_tm: float
    ppp_historico_usd_tm: float
    precio_objetivo_usd_tm: float
    precio_techo_usd_tm: float
    estrategia_sourcing: str
    argumento_negociacion: str

class ListaEstrategia(BaseModel):
    estrategias: List[ItemEstrategia]

class ItemOfertaEvaluada(BaseModel):
    proveedor: str
    producto: str
    codigo_erp_mapeado: str = Field(default="N/A", description="Código de material reconocido del ERP")
    producto_historico_relacionado: str = Field(default="", description="Descripción histórica asociada")
    concentracion_detectada: str
    presentacion_cotizada: str
    precio_original_cotizado: str
    precio_ofertado_usd_tm: float
    precio_techo_referencia_usd_tm: float
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
    concentracion: str
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
            raise ValueError("No se encontraron columnas de Código (Material) ni de Descripción (Texto breve).")

        if not col_desc:
            col_desc = col_cod
        if not col_cod:
            col_cod = col_desc

        if not col_cant or (not col_precio and not col_total):
            raise ValueError("El archivo Excel debe contener columnas de Cantidad y Precio/Total.")

        df = df.dropna(subset=[col_cant]).copy()
        df[col_cant] = pd.to_numeric(df[col_cant], errors="coerce").fillna(0)

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

        if col_total and col_total in df.columns:
            df["gasto_usd"] = pd.to_numeric(df[col_total], errors="coerce").fillna(0)
        else:
            df["precio_num"] = pd.to_numeric(df[col_precio], errors="coerce").fillna(0)
            def calcular_gasto(row):
                um = str(row[col_um]).lower() if col_um and pd.notna(row[col_um]) else "kg"
                p = row["precio_num"]
                cant = row[col_cant]
                if "tm" in um or "ton" in um:
                    return row["volumen_tm"] * p
                else:
                    return cant * p
            df["gasto_usd"] = df.apply(calcular_gasto, axis=1)

        group_cols = [col_cod, col_desc] if col_cod != col_desc else [col_desc]
        resumen = df.groupby(group_cols).agg(
            volumen_total_comprado_tm=("volumen_tm", "sum"),
            gasto_total_acumulado_usd=("gasto_usd", "sum")
        ).reset_index()

        resumen = resumen[resumen["volumen_total_comprado_tm"] > 0].copy()
        resumen["ppp_anterior_usd_tm"] = (resumen["gasto_total_acumulado_usd"] / resumen["volumen_total_comprado_tm"]).round(2)

        resumen = resumen.rename(columns={
            col_cod: "codigo_erp",
            col_desc: "descripcion_historica",
            "volumen_total_comprado_tm": "volumen_historico_tm"
        })

        return resumen[["codigo_erp", "descripcion_historica", "volumen_historico_tm", "ppp_anterior_usd_tm"]]

    def ejecutar_licitacion_completa(self, pedidos_crudos: str, data_historica: dict, cotizaciones_crudas: str = "", archivos_pdf: list = None, datos_excel: str = ""):
        if archivos_pdf is None:
            archivos_pdf = []
        self.total_tokens_consumidos = 0

        # 1. Agente Consolidador
        prompt_agente1 = """
        Consolidador Agroindustrial:
        - NUNCA agrupes insumos bajo un nombre genérico si su concentración (%) o especificación técnica difiere.
        - Refleja la concentración o modelo en 'concentracion_o_grado' y en 'producto_estandarizado'.
        - Identifica el estado_fisico ('solido', 'liquido' o 'unidad').
        - Convierte a KG o unidades correspondientes.
        """
        pedidos_dict = self._invocar_gemini_schema(prompt_agente1, pedidos_crudos, ListaDemanda)
        df_pedidos = pd.DataFrame(pedidos_dict.get("pedidos", []))

        resumen_demanda = df_pedidos.groupby(["producto_estandarizado", "concentracion_o_grado", "estado_fisico"]).agg(
            Volumen_Total_KG=("volumen_total_kg", "sum"),
            Nro_Pedidos=("agricultor", "count")
        ).reset_index()
        resumen_demanda["Volumen_Total_TM"] = resumen_demanda["Volumen_Total_KG"] / 1000

        time.sleep(1)

        # 2. Agente Estratega
        df_hist = pd.DataFrame(data_historica)
        demanda_compacta = resumen_demanda[['producto_estandarizado', 'concentracion_o_grado', 'Volumen_Total_TM']].to_csv(index=False, sep="|")
        hist_compacto = df_hist.to_csv(index=False, sep="|")
        
        prompt_agente2 = """
        Estratega de Compras: Cruza demanda e histórico PPP.
        - Asocia el codigo_historico del ERP exacto analizando 'codigo_erp' y 'descripcion_historica'.
        - Fija precio techo y objetivo considerando escala de volumen.
        """
        ctx_estratega = f"DEMANDA:\n{demanda_compacta}\nHISTÓRICO_CON_PPP:\n{hist_compacto}"
        estrategia_dict = self._invocar_gemini_schema(prompt_agente2, ctx_estratega, ListaEstrategia)
        df_estrategia = pd.DataFrame(estrategia_dict.get("estrategias", []))

        time.sleep(1)

        # 3. Agente Evaluador y Auditor Legal
        techo_compacto = df_estrategia[['codigo_historico', 'producto', 'concentracion', 'precio_techo_usd_tm', 'precio_objetivo_usd_tm']].to_csv(index=False, sep="|")
        prompt_agente3 = """
        Evaluador Técnico-Legal:
        - Homologa precios de proformas a USD/TM o USD/Unidad.
        - Mapea al 'codigo_erp_mapeado' y 'producto_historico_relacionado' exacto.
        - Extrae 'concentracion_detectada'.
        - Audita penalidades, moras, tolerancias y logística. Asigna nivel_riesgo_contractual (BAJO, MEDIO, ALTO).
        """
        
        ctx_evaluador = [f"CATALOGO_TECHOS:\n{techo_compacto}"]
        if cotizaciones_crudas.strip():
            ctx_evaluador.append(f"TEXTO:\n{cotizaciones_crudas}")
        if datos_excel.strip():
            ctx_evaluador.append(f"EXCEL_PROFORMAS:\n{datos_excel}")
        for pdf in archivos_pdf:
            ctx_evaluador.append(types.Part.from_bytes(data=pdf["bytes"], mime_type="application/pdf"))

        proformas_dict = self._invocar_gemini_schema(prompt_agente3, ctx_evaluador, ListaOfertasEvaluadas)
        df_proformas = pd.DataFrame(proformas_dict.get("ofertas", []))

        time.sleep(1)

        # 4. Agente Orquestador (TCO y Dictamen)
        eval_compacta = df_proformas[['proveedor', 'producto', 'concentracion_detectada', 'codigo_erp_mapeado', 'precio_ofertado_usd_tm', 'nivel_riesgo_contractual', 'penalidades_y_moras']].to_csv(index=False, sep="|")
        prompt_agente4 = """
        Director Compras TCO: Adjudica por producto y especificación.
        - Si el menor precio tiene riesgo ALTO por penalidades abusivas, adjudica al siguiente postor seguro.
        - Redacta condiciones de blindaje para la Orden de Compra.
        """
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
