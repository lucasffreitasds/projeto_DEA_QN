"""Pipeline de eficiência (DEA) dos eventos QN.

Mesma lógica do notebook projeto_DEA_QN.ipynb, organizada em funções para o notebook e o
app (app.py) usarem exatamente o mesmo cálculo:

    planilha -> padronizar colunas e números -> criar inputs/output -> DEA (CCR, BCC, RNC)
"""
import pandas as pd
from Pyfrontier.frontier_model import EnvelopDEA as fm

# ---------------------------------------------------------------- colunas usadas
COL_ID = 'Evento_ID'
COLUNAS_OBRIGATORIAS = [COL_ID, 'Custo_Estrutura', 'Custo_Equipe', 'Custo_Atracoes', 'Insumos',
                        'Publico', 'Receita_Bar', 'Receita_Bilheteria']

# nomes alternativos aceitos na planilha (a base original tem 'Receita_Bilheria')
APELIDOS = {'Receita_Bilheria': 'Receita_Bilheteria'}

# variáveis do DEA
COLS_INPUTS = ['Custo_Estrutura_Total', 'Custo_Atracoes', 'Insumos']
COLS_OUTPUT = ['Receita_Total']
NOMES_INPUTS = ['estrutura', 'atracoes', 'insumos']
ROTULOS_INPUTS = {'estrutura': 'Estrutura + equipe', 'atracoes': 'Atrações', 'insumos': 'Insumos'}

ORIENTACOES = {'in': 'Insumo: quanto daria para gastar a menos',
               'out': 'Output: quanto daria para faturar a mais'}


# ---------------------------------------------------------------- preparação
def preparar(df_bruto: pd.DataFrame) -> pd.DataFrame:
    """Padroniza nomes de colunas e converte números com vírgula decimal ('11703,25') em float."""
    df = df_bruto.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns=APELIDOS)
    numericas = df.columns.drop(COL_ID, errors='ignore')
    texto = df[numericas].select_dtypes(exclude='number').columns
    df[texto] = df[texto].replace(',', '.', regex=True).apply(pd.to_numeric, errors='coerce')
    df[COL_ID] = df[COL_ID].astype(str)
    return df


def validar_planilha(df: pd.DataFrame) -> list:
    """Lista das colunas obrigatórias que estão faltando (vazia se a planilha serve)."""
    return [c for c in COLUNAS_OBRIGATORIAS if c not in df.columns]


def criar_variaveis(df: pd.DataFrame) -> pd.DataFrame:
    """Cria os inputs/output do DEA e os indicadores por pessoa. Cada real de custo entra uma vez só."""
    df = df.copy()
    df['Receita_Total'] = df['Receita_Bar'] + df['Receita_Bilheteria']
    df['Custo_Estrutura_Total'] = df['Custo_Estrutura'] + df['Custo_Equipe']
    df['Custo_Total'] = df[COLS_INPUTS].sum(axis=1)
    df['receita_por_pessoa'] = df['Receita_Total'] / df['Publico']
    df['atracao_por_pessoa'] = df['Custo_Atracoes'] / df['Publico']
    df['custo_por_pessoa'] = df['Custo_Total'] / df['Publico']
    if 'Lucro' in df.columns:
        # lucro informado x receita - custos: diferença = receitas/custos que não estão na planilha
        df['diferenca_lucro'] = df['Receita_Total'] - df['Custo_Total'] - df['Lucro']
    return df


def marcar_exclusoes(df: pd.DataFrame, exclusoes: dict) -> pd.DataFrame:
    """Marca quem fica fora do DEA: exclusões manuais + qualquer input/output vazio, zero ou negativo."""
    df = df.copy()
    motivos = pd.Series('', index=df.index)
    for evento, motivo in exclusoes.items():
        motivos[df[COL_ID] == evento] = motivo
    rotulos = {'Custo_Estrutura_Total': 'estrutura + equipe', 'Custo_Atracoes': 'atrações',
               'Insumos': 'insumos', 'Receita_Total': 'receita total'}
    for col, rotulo in rotulos.items():
        invalido = ~(df[col] > 0) & (motivos == '')          # ~(> 0) também pega valores vazios
        motivos[invalido] = f'{rotulo} vazio, zero ou negativo (o DEA exige valores positivos)'
    df['motivo_exclusao'] = motivos
    return df


def checar_cooper(n: int) -> dict:
    """Regra de Cooper, Seiford & Tone (2007): n >= max{m x s, 3 x (m + s)}."""
    m, s = len(COLS_INPUTS), len(COLS_OUTPUT)
    minimo = max(m * s, 3 * (m + s))
    return {'n': n, 'minimo': minimo, 'ok': n >= minimo}


# ---------------------------------------------------------------- DEA
def rodar_dea(df: pd.DataFrame, retorno: str = 'CRS', orientacao: str = 'in'):
    """DEA. retorno: 'CRS' (CCR), 'VRS' (BCC), 'NIRS' (RNC). orientacao: 'in' ou 'out'.

    O Pyfrontier devolve score <= 1 na orientação a insumo e score >= 1 (φ) a output.
    Aqui 'score' é sempre a eficiência de 0 a 1 (a output, 1/φ), para as duas leituras serem comparáveis.
    Devolve (modelo, tabela com score, peers, folgas, metas de custo e de receita).
    """
    X = df[COLS_INPUTS].to_numpy(dtype=float)
    Y = df[COLS_OUTPUT].to_numpy(dtype=float)
    eventos = df[COL_ID].tolist()

    modelo = fm(retorno, orientacao)
    modelo.fit(X, Y)

    linhas = []
    for i, r in enumerate(modelo.result):
        eficiencia = r.score if orientacao == 'in' else 1 / r.score
        meta_x = r.virtual_dmu.input                    # custos-alvo
        meta_y = r.virtual_dmu.output[0]                # receita-alvo
        linha = {
            'evento': eventos[i],
            'score': round(eficiencia, 3),
            # eficiência forte: score 1 e sem folga (tolerância por causa do ruído do solver)
            'eficiente': eficiencia >= 1 - 1e-6 and sum(r.x_slack) <= 1e-4 * X[i].sum(),
            'peers_pesos': {eventos[j]: round(w, 2) for j, w in enumerate(r.weights) if w > 1e-6},
        }
        for k, nome in enumerate(NOMES_INPUTS):
            linha[f'atual_{nome}'] = round(X[i, k])
            linha[f'folga_{nome}'] = round(max(r.x_slack[k], 0))
            linha[f'meta_{nome}'] = round(meta_x[k])
            linha[f'reducao_%_{nome}'] = round(max(1 - meta_x[k] / X[i, k], 0) * 100, 1)

        custo_atual, custo_meta = X[i].sum(), meta_x.sum()
        linha['custo_atual'] = round(custo_atual)
        linha['custo_meta'] = round(custo_meta)
        linha['economia_potencial'] = round(max(custo_atual - custo_meta, 0))
        linha['economia_%'] = round(max(custo_atual - custo_meta, 0) / custo_atual * 100, 1)

        receita_atual = Y[i, 0]
        linha['receita_atual'] = round(receita_atual)
        linha['receita_meta'] = round(max(meta_y, receita_atual))
        linha['ganho_receita'] = round(max(meta_y - receita_atual, 0))
        linha['ganho_%'] = round(max(meta_y - receita_atual, 0) / receita_atual * 100, 1)
        linhas.append(linha)

    tabela = pd.DataFrame(linhas).sort_values('score', ascending=False).reset_index(drop=True)
    return modelo, tabela


def tipo_retorno(linha) -> str:
    if abs(linha['escala'] - 1) < 1e-3:
        return 'Constante'
    if abs(linha['RNC'] - linha['BCC']) < 1e-3:
        return 'Decrescente'      # RNC = BCC -> já passou do tamanho ideal
    return 'Crescente'            # RNC != BCC -> pequeno demais


def diagnostico(linha) -> str:
    if linha['CCR'] >= 0.999:
        return 'Eficiente'
    if linha['BCC'] >= 0.999:
        return 'Escala'
    return 'Gestão' if linha['escala'] >= linha['BCC'] else 'Escala'   # o componente menor é o problema principal


def analise_completa(df: pd.DataFrame, orientacao: str = 'in') -> dict:
    """CCR, BCC e RNC. Devolve {'ccr', 'bcc', 'comparacao'}."""
    _, df_ccr = rodar_dea(df, 'CRS', orientacao)
    _, df_bcc = rodar_dea(df, 'VRS', orientacao)
    _, df_rnc = rodar_dea(df, 'NIRS', orientacao)

    comparacao = (df_ccr[['evento', 'score']].rename(columns={'score': 'CCR'})
                  .merge(df_bcc[['evento', 'score']].rename(columns={'score': 'BCC'}), on='evento')
                  .merge(df_rnc[['evento', 'score']].rename(columns={'score': 'RNC'}), on='evento'))
    comparacao['escala'] = (comparacao['CCR'] / comparacao['BCC']).round(3)
    comparacao['retorno'] = comparacao.apply(tipo_retorno, axis=1)
    comparacao['problema_principal'] = comparacao.apply(diagnostico, axis=1)
    # no BCC, quem tem o MENOR valor da base em algum custo (ou a menor receita) sai com score 1 quase
    # automaticamente: não existe evento ou combinação de eventos menor para compará-lo
    rotulos = {'Custo_Estrutura_Total': 'menor estrutura + equipe', 'Custo_Atracoes': 'menor custo de atrações',
               'Insumos': 'menores insumos', 'Receita_Total': 'menor receita'}
    extremos = {}
    for col, rotulo in rotulos.items():
        evento_min = df.loc[df[col].idxmin(), COL_ID]
        extremos.setdefault(evento_min, []).append(rotulo)
    comparacao['extremo_em'] = comparacao['evento'].map(lambda e: ', '.join(extremos.get(e, [])))
    comparacao['bcc_por_extremo'] = ((comparacao['BCC'] >= 0.999) & (comparacao['CCR'] < 0.999)
                                     & (comparacao['extremo_em'] != ''))
    comparacao = comparacao.merge(
        df_ccr[['evento', 'custo_atual', 'economia_potencial', 'economia_%', 'receita_atual', 'ganho_receita', 'ganho_%']],
        on='evento')
    comparacao = comparacao.sort_values('CCR', ascending=False).reset_index(drop=True)
    return {'ccr': df_ccr, 'bcc': df_bcc, 'comparacao': comparacao}


# ---------------------------------------------------------------- pipeline completo
def pipeline(df_bruto: pd.DataFrame, orientacao: str = 'in', exclusoes: dict = None) -> dict:
    """Da planilha bruta aos resultados.

    Devolve {'eventos': tabela com variáveis, indicadores e motivo de exclusão,
             'resultado': {'ccr', 'bcc', 'comparacao'}, 'cooper': {...}}.
    """
    df = preparar(df_bruto)
    faltando = validar_planilha(df)
    if faltando:
        raise ValueError(f'Colunas obrigatórias ausentes: {faltando}')
    df = criar_variaveis(df)
    df = marcar_exclusoes(df, exclusoes or {})

    no_dea = df[df['motivo_exclusao'] == ''].reset_index(drop=True)
    if len(no_dea) < 2:
        raise ValueError('Menos de 2 eventos válidos: não dá para rodar o DEA.')
    return {'eventos': df, 'resultado': analise_completa(no_dea, orientacao),
            'cooper': checar_cooper(len(no_dea))}
