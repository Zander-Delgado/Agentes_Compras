import time
import json
import pandas as pd
from google import genai
from google.genai import types

class CentralComprasAI:
    def __init__(self, api_key: str, modelo: str = "gemini-3.8-flash"):
        self.client = genai.Client(api_key=api_key)
        self.modelo = modelo

    def _invocar_gemini_json(self, system_prompt: str, contents_input, max_intentos: int = 4):
        for i in range(max_intentos):
            try:
                response = self.client.models.generate_content(
                    model=self.modelo,
                    contents=contents_input,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json"
                    )
                )
                return json.loads(response.text)
            except Exception as e:
                if i < max_intentos - 1:
                    time.sleep(5)
                else:
                    raise e

    def ejecutar_licitacion_completa(self, pedidos_crudos: str, data_historica: dict, cotizaciones_crudas: str = "", archivos_pdf: list = None, datos_excel: str = ""):
        if archivos_pdf is None:
            archivos_pdf = []

        # 1. Agente Consolidador
        prompt_agente1 = """
        Eres el Agente Consolidador de Compras Agrícolas. Normaliza pedidos informales:
        - Homologa nombres a estándar de fertilizantes comerciales.
        - Convierte todas las cantidades a KG (1 saco/bolsa = 50 kg, 1 TM = 1000 kg).
        - Si no se especifica agricultor/fundo, pon 'No especificado'.
        Responde ÚNICAMENTE un array JSON con claves:
        [{"agricultor": "", "fundo": "", "producto_solicitado": "", "producto_estandarizado": "", "cantidad_original": 0.0, "unidad_original": "", "volumen_total_kg": 0.0}]
        """
        pedidos_json = self._invocar_gemini_json(prompt_agente1, pedidos_crudos)
        df_pedidos = pd.DataFrame(pedidos_json)

        resumen_demanda = df_pedidos.groupby("producto_estandarizado").agg(
            Volumen_Total_KG=("volumen_total_kg", "sum"),
            Nro_Pedidos=("agricultor", "count")
        ).reset_index()
        resumen_demanda["Volumen_Total_TM"] = resumen_demanda["Volumen_Total_KG"] / 1000

        # 2. Agente Estratega
        df_hist = pd.DataFrame(data_historica)
        prompt_agente2 = """
        Eres el Agente Estratega de Precios. Con la demanda y el histórico (PPP en USD/TM):
        - Fija Precio Techo (USD/TM) y Precio Objetivo con descuento por volumen.
        - Define Estrategia de Sourcing y Argumento de Negociación.
        Responde ÚNICAMENTE un array JSON con claves:
        [{"producto": "", "volumen_tm": 0.0, "ppp_historico_usd_tm": 0.0, "precio_objetivo_usd_tm": 0.0, "precio_techo_usd_tm": 0.0, "estrategia_sourcing": "", "argumento_negociacion": ""}]
        """
        ctx_estratega = f"DEMANDA:\n{resumen_demanda[['producto_estandarizado', 'Volumen_Total_TM']].to_string(index=False)}\nHISTÓRICO:\n{df_hist.to_string(index=False)}"
        estrategia_json = self._invocar_gemini_json(prompt_agente2, ctx_estratega)
        df_estrategia = pd.DataFrame(estrategia_json)

        # 3. Agente Evaluador de Proformas y Auditor Contractual
        prompt_agente3 = """
        Eres el Agente Evaluador Técnico-Legal de Compras Agrícolas.
        Analiza las ofertas comerciales, proformas en PDF, listas en Excel o textos.
        Examina meticulosamente las hojas de términos, condiciones comerciales y letra chica:
        - Homogeniza todo precio a 'precio_ofertado_usd_tm' (si es saco 50kg en USD, multiplica por 20; si ya viene en USD/TM úsalo directo).
        - Evalúa si el precio es ADMISIBLE o FUERA DE RANGO contra el precio techo.
        - Calcula desviación: ((precio_ofertado - precio_techo) / precio_techo) * 100.
        - Identifica PENALIDADES Y MORAS: multas por demora en descarga, sobrestadías de transporte, intereses por mora en pago, tolerancias de merma.
        - Identifica RESTRICCIONES LOGÍSTICAS: mínimos de pedido (MOQ), tipo de camión requerido, vigencia de cotización, condiciones de descarga/estiba.
        - Asigna nivel_riesgo_contractual: 'BAJO' (condiciones estándar de mercado), 'MEDIO' (condiciones rígidas o plazos cortos), 'ALTO' (penalidades abusivas, pago 100% anticipado o riesgo operativo severo).

        Responde ÚNICAMENTE un array JSON con claves:
        [
          {
            "proveedor": "",
            "producto": "",
            "presentacion_cotizada": "",
            "precio_original_cotizado": "",
            "precio_ofertado_usd_tm": 0.0,
            "precio_techo_referencia_usd_tm": 0.0,
            "desviacion_vs_techo_%": 0.0,
            "estado_precio": "",
            "condiciones_pago": "",
            "lugar_entrega": "",
            "dias_entrega": 0,
            "penalidades_y_moras": "",
            "restricciones_logisticas": "",
            "nivel_riesgo_contractual": ""
          }
        ]
        """
        
        ctx_evaluador = [
            f"PRECIOS TECHO DE REFERENCIA:\n{df_estrategia[['producto', 'precio_techo_usd_tm', 'precio_objetivo_usd_tm']].to_string(index=False)}"
        ]
        
        if cotizaciones_crudas.strip():
            ctx_evaluador.append(f"\nCOTIZACIONES EN TEXTO:\n{cotizaciones_crudas}")
            
        if datos_excel.strip():
            ctx_evaluador.append(f"\nCOTIZACIONES Y CLÁUSULAS DE EXCEL:\n{datos_excel}")

        for pdf in archivos_pdf:
            ctx_evaluador.append(types.Part.from_bytes(data=pdf["bytes"], mime_type="application/pdf"))

        proformas_json = self._invocar_gemini_json(prompt_agente3, ctx_evaluador)
        df_proformas = pd.DataFrame(proformas_json)

        # 4. Agente Orquestador (TCO y Dictamen Legal)
        prompt_agente4 = """
        Eres el Agente Director de Compras y Riesgo Corporativo.
        Emite la adjudicación final considerando el Costo Total de Adquisición (TCO) y no solo el precio facial:
        - Si un proveedor tiene el precio más bajo pero su 'nivel_riesgo_contractual' es ALTO por penalidades leoninas o condiciones logísticas imposibles, puedes adjudicar al segundo mejor postor explicando el riesgo mitigado.
        - En 'observaciones_contractuales_oc', detalla qué cláusulas deben condicionarse o blindarse en la orden de compra.
        - En 'comunicacion_formal', redacta una confirmación profesional aceptando la oferta comercial pero exigiendo la eliminación o ajuste de cualquier cláusula/penalidad desproporcionada.

        Responde ÚNICAMENTE un objeto JSON:
        {
          "resumen_adjudicacion": [
            {
              "producto": "",
              "volumen_tm": 0.0,
              "proveedor_ganador": "",
              "precio_final_usd_tm": 0.0,
              "gasto_total_usd": 0.0,
              "gasto_techo_usd": 0.0,
              "ahorro_generado_usd": 0.0,
              "riesgo_contractual": "",
              "justificacion_decision": "",
              "observaciones_contractuales_oc": ""
            }
          ],
          "ahorro_total_consolidado_usd": 0.0,
          "dictamen_riesgo_global": "",
          "comunicacion_formal": {"asunto": "", "cuerpo_correo": ""}
        }
        """
        ctx_orquestador = f"DEMANDA:\n{resumen_demanda[['producto_estandarizado', 'Volumen_Total_TM']].to_string(index=False)}\nEVALUACIÓN INTEGRAL:\n{df_proformas.to_string(index=False)}"
        resultado_adjudicacion = self._invocar_gemini_json(prompt_agente4, ctx_orquestador)

        return {
            "demanda_consolidada": resumen_demanda,
            "estrategia_precios": df_estrategia,
            "cuadro_comparativo": df_proformas,
            "adjudicacion": pd.DataFrame(resultado_adjudicacion["resumen_adjudicacion"]),
            "ahorro_total_usd": resultado_adjudicacion["ahorro_total_consolidado_usd"],
            "dictamen_riesgo": resultado_adjudicacion.get("dictamen_riesgo_global", "Evaluación completada."),
            "comunicacion_cierre": resultado_adjudicacion["comunicacion_formal"]
        }
