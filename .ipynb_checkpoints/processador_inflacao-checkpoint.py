# -*- coding: utf-8 -*-
"""
processador_inflacao.py
Processamento automático do IPCA por estratos de renda.
Compatibilizado com gerador_graficos.py e com os pesos da POF.
"""

import os
import unicodedata
import pandas as pd
import numpy as np
import sidrapy

# ==============================================================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS
# ==============================================================================
BASE_DIR = r"C:\Users\ITAIGUARA\Dropbox\Relatorio_IPCA_Domicilio_Renda"
CAMINHO_PESOS = os.path.join(BASE_DIR, "pesos_pof_normalizados.parquet")

# Nomes conforme as colunas do seu arquivo parquet de pesos
COLUNAS_PARQUET = [
    'Renda Muito Baixa',
    'Renda Baixa',
    'Renda Média-Baixa',
    'Renda Média',
    'Renda Média-Alta',
    'Renda Alta'
]

# Nomes oficiais esperados pelo gerador de gráficos
ESTRATOS_GRAFICO = [
    'Até 3 SM',
    '3 a 6 SM',
    '6 a 10 SM',
    '10 a 15 SM',
    '15 a 25 SM',
    '> 25 SM'
]

# Relação entre os nomes dos subgrupos do relatório e os códigos de consulta da Tabela 7060
SUBGRUPOS_ALIMENTACAO = {
    'Cereais e leguminosas':      '7172',
    'Farinhas, féculas e massas': '7173',
    'Tubérculos e raízes':        '7174',
    'Açúcares e derivados':       '7175',
    'Hortaliças e verduras':      '7176',
    'Frutas':                     '7177',
    'Carnes':                     '7178',
    'Pescados':                   '7179',
    'Peixes e carnes processadas':'7180',
    'Aves e ovos':                '7181',
    'Leites e derivados':         '7182',
    'Panificados':                '7183',
    'Óleos e gorduras':           '7184',
    'Bebidas e infusões':         '7185',
    'Enlatados e conservas':      '7186',
    'Sal e condimentos':          '7187'
}

# Prefixos dos códigos oficiais dos subitens do IBGE (POF)
PREFIXOS_POF = {
    'Cereais e leguminosas':      '1101',
    'Farinhas, féculas e massas': '1102',
    'Tubérculos e raízes':        '1103',
    'Açúcares e derivados':       '1104',
    'Hortaliças e verduras':      '1105',
    'Frutas':                     '1106',
    'Carnes':                     '1107',
    'Pescados':                   '1108',
    'Peixes e carnes processadas':'1109',
    'Aves e ovos':                '1110',
    'Leites e derivados':         '1111',
    'Panificados':                '1112',
    'Óleos e gorduras':           '1113',
    'Bebidas e infusões':         '1114',
    'Enlatados e conservas':      '1115',
    'Sal e condimentos':          '1116'
}


# ==============================================================================
# 2. CARREGAMENTO DOS PESOS DA POF
# ==============================================================================
def carregar_pesos_pof(caminho=CAMINHO_PESOS):
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"Arquivo não localizado em: {caminho}")

    try:
        df_pesos = pd.read_parquet(caminho, engine="fastparquet")
    except Exception:
        try:
            import pyarrow.parquet as pq
            df_pesos = pq.read_table(caminho).to_pandas()
        except Exception:
            df_pesos = pd.read_parquet(caminho, engine="pyarrow")

    df_pesos['codigo_subitem'] = df_pesos['codigo_subitem'].astype(str).str.strip()
    df_pesos = df_pesos.set_index('codigo_subitem')[COLUNAS_PARQUET]
    df_pesos.columns = ESTRATOS_GRAFICO
    return df_pesos


# ==============================================================================
# 3. CRIAÇÃO DINÂMICA DA PASTA DA EDIÇÃO
# ==============================================================================
def obter_pasta_edicao(mes_ano_str, pasta_raiz=BASE_DIR):
    texto_limpo = unicodedata.normalize('NFKD', mes_ano_str).encode('ASCII', 'ignore').decode('utf-8').lower()
    partes = texto_limpo.split()
    mes = partes[0]
    ano = partes[1] if len(partes) > 1 else ""

    nome_pasta = f"edicao_{mes}_{ano}" if ano else f"edicao_{mes}"
    caminho_pasta = os.path.join(pasta_raiz, nome_pasta)
    os.makedirs(caminho_pasta, exist_ok=True)
    return caminho_pasta


# ==============================================================================
# 4. EXTRAÇÃO OFICIAL DO SIDRA (TABELA 7060)
# ==============================================================================
def extrair_dados_completos_sidra(periodo="last 6"):
    print(f"Consultando Tabela 7060 do SIDRA para o período: {periodo}...")

    # 7169 = IPCA Geral, 7170 = Alimentação e Bebidas, 7171 = Alimentação no Domicílio
    codigos_consulta = ",".join(
        ["7169", "7170", "7171"] + list(SUBGRUPOS_ALIMENTACAO.values())
    )

    dados_brutos = sidrapy.get_table(
        table_code="7060",
        territorial_level="1",
        ibge_territorial_code="all",
        variable="63",
        period=periodo,
        classifications={"315": codigos_consulta},
    )

    df = pd.DataFrame(dados_brutos)
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df_limpo = df[[
        "Mês (Código)",
        "Mês",
        "Geral, grupo, subgrupo, item e subitem (Código)",
        "Geral, grupo, subgrupo, item e subitem",
        "Valor",
    ]].copy()

    df_limpo.columns = [
        "mes_codigo",
        "mes_nome",
        "subitem_codigo",
        "subitem_nome",
        "variacao_mensal",
    ]

    df_limpo["variacao_mensal"] = (
        df_limpo["variacao_mensal"]
        .astype(str)
        .str.replace("...", "0.0", regex=False)
        .str.replace("-", "0.0", regex=False)
        .str.replace(",", ".", regex=False)
    )
    df_limpo["variacao_mensal"] = pd.to_numeric(
        df_limpo["variacao_mensal"], errors="coerce"
    ).fillna(0.0)

    return df_limpo


# ==============================================================================
# 5. CÁLCULO E CONSTRUÇÃO DAS ESTRUTURAS DE DADOS
# ==============================================================================
def processar_calculos_relatorio(periodo="last 6"):
    df_pesos_subitens = carregar_pesos_pof()
    df_sidra = extrair_dados_completos_sidra(periodo=periodo)
    meses_disponiveis = df_sidra['mes_nome'].unique()

    # Mapeamento e agregação dos pesos no nível de subgrupo
    pesos_agregados_dict = {}
    for nome_cat, prefixo in PREFIXOS_POF.items():
        filtro = df_pesos_subitens.index.str.startswith(prefixo)
        if filtro.any():
            pesos_agregados_dict[nome_cat] = df_pesos_subitens[filtro].sum()
        else:
            pesos_agregados_dict[nome_cat] = pd.Series(0.0, index=ESTRATOS_GRAFICO)

    df_pesos_subgrupos = pd.DataFrame(pesos_agregados_dict).T
    # Normalização dos pesos para soma 1.0 por coluna de estrato
    somas_pesos = df_pesos_subgrupos.sum(axis=0)
    df_pesos_normalizados = df_pesos_subgrupos.div(somas_pesos, axis=1).fillna(0.0)

    mapa_meses_abrev = {
        'janeiro': 'Jan', 'fevereiro': 'Fev', 'março': 'Mar', 'abril': 'Abr',
        'maio': 'Mai', 'junho': 'Jun', 'julho': 'Jul', 'agosto': 'Ago',
        'setembro': 'Set', 'outubro': 'Out', 'novembro': 'Nov', 'dezembro': 'Dez'
    }

    nomes_meses_formatados = []
    series_historicas = {estrato: [] for estrato in ESTRATOS_GRAFICO}
    ipca_geral_historico = []

    for mes in meses_disponiveis:
        mes_puro = mes.split()[0].lower()
        nomes_meses_formatados.append(mapa_meses_abrev.get(mes_puro, mes_puro[:3].capitalize()))

        df_mes = df_sidra[df_sidra['mes_nome'] == mes]

        # IPCA Geral
        ipca_geral_linha = df_mes[df_mes['subitem_codigo'] == '7169']
        ipca_val = ipca_geral_linha['variacao_mensal'].values[0] if not ipca_geral_linha.empty else 0.0
        ipca_geral_historico.append(ipca_val)

        # Extração das variações de cada subgrupo
        variacoes_subgrupos = pd.Series(0.0, index=df_pesos_normalizados.index)
        for nome_cat, cod_sidra in SUBGRUPOS_ALIMENTACAO.items():
            linha = df_mes[df_mes['subitem_codigo'] == cod_sidra]
            if not linha.empty:
                variacoes_subgrupos[nome_cat] = linha['variacao_mensal'].values[0]

        # Inflação ponderada por estrato de renda
        for estrato in ESTRATOS_GRAFICO:
            taxa_estrato = (df_pesos_normalizados[estrato] * variacoes_subgrupos).sum()
            series_historicas[estrato].append(round(taxa_estrato, 2))

    # Mês mais recente
    mes_atual_nome = meses_disponiveis[-1]
    df_mes_atual = df_sidra[df_sidra['mes_nome'] == mes_atual_nome]

    # Variações do mês mais recente
    variacoes_atuais = pd.Series(0.0, index=df_pesos_normalizados.index)
    for nome_cat, cod_sidra in SUBGRUPOS_ALIMENTACAO.items():
        linha = df_mes_atual[df_mes_atual['subitem_codigo'] == cod_sidra]
        if not linha.empty:
            variacoes_atuais[nome_cat] = linha['variacao_mensal'].values[0]

    # Decomposição marginal (Até 3 SM vs > 25 SM) com coluna 'categoria' para o gráfico 3
    decomposicao_itens = []
    for nome_cat in df_pesos_normalizados.index:
        peso_baixa = df_pesos_normalizados.loc[nome_cat, 'Até 3 SM']
        peso_alta = df_pesos_normalizados.loc[nome_cat, '> 25 SM']
        var_item = variacoes_atuais.get(nome_cat, 0.0)
        contrib = (peso_baixa - peso_alta) * var_item

        decomposicao_itens.append({
            'categoria': nome_cat,
            'peso_baixa': round(peso_baixa * 100, 2),
            'peso_alta': round(peso_alta * 100, 2),
            'variacao_mes': round(var_item, 2),
            'contrib_marginal': round(contrib, 3)
        })

    df_decomposicao = pd.DataFrame(decomposicao_itens).sort_values(by='contrib_marginal', ascending=False)
    pasta_edicao = obter_pasta_edicao(mes_atual_nome, BASE_DIR)

    return {
        'pasta_edicao': pasta_edicao,
        'mes_atual': mes_atual_nome.capitalize(),
        'meses_eixo_x': nomes_meses_formatados,
        'series_historicas': series_historicas,
        'ipca_geral_mes': f"{ipca_geral_historico[-1]:+.2f}".replace('.', ','),
        'decomposicao': df_decomposicao,
        'variacoes_mes_atual': [series_historicas[e][-1] for e in ESTRATOS_GRAFICO]
    }


# ==============================================================================
# 6. EXECUÇÃO
# ==============================================================================
if __name__ == "__main__":
    resultado = processar_calculos_relatorio(periodo="last 6")

    print("\n============================================================")
    print(f"RESULTADOS CALCULADOS PARA: {resultado['mes_atual']}")
    print(f"Diretório da Edição: {resultado['pasta_edicao']}")
    print("============================================================\n")

    print(f"IPCA Geral do Mês: {resultado['ipca_geral_mes']}%\n")

    print("1. Inflação por Estrato de Renda no Mês Mais Recente:")
    for estrato, valor in zip(ESTRATOS_GRAFICO, resultado['variacoes_mes_atual']):
        print(f" - {estrato}: {valor:+.2f}%")

    print("\n2. Principais Itens na Decomposição Marginal (Até 3 SM vs. > 25 SM):")
    print(resultado['decomposicao'].head(10).to_string(index=False))