"""Painel de eficiência (DEA) dos eventos QN.

Rodar localmente:
    streamlit run app.py

A planilha em uso é, nesta ordem: a enviada na sessão, a publicada pelo técnico
(dados/planilha_atual.*) ou a original (dataset/EDA_QN.csv).

Acesso: login e senha cadastrados em .streamlit/secrets.toml (ver secrets.toml.example e auth.py).
Perfis: 'leitor' vê o painel; 'tecnico' também atualiza a planilha.
"""
import datetime
import io
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import dea

PASTA = Path(__file__).parent
PLANILHA_ORIGINAL = PASTA / 'dataset' / 'EDA_QN.csv'
PASTA_PUBLICADA = PASTA / 'dados'

# cores por diagnóstico: ordem fixa da paleta categórica (slots 1-3), nunca recicladas
CORES = {'Eficiente': '#2a78d6', 'Escala': '#eb6834', 'Gestão': '#1baf7a'}
CORES_SERIE = {'Atual': '#2a78d6', 'Meta': '#eb6834'}
COR_UNICA = '#2a78d6'

st.set_page_config(page_title='Eficiência dos Eventos', page_icon='🎪', layout='wide')


# ======================================================================= login
def usuarios_cadastrados() -> dict:
    """{login: {'senha_hash': ..., 'perfil': ...}} lido do .streamlit/secrets.toml."""
    try:
        return {login: dict(dados) for login, dados in st.secrets.get('usuarios', {}).items()}
    except Exception:                       # sem secrets.toml
        return {}


def tela_de_login():
    """Mostra o formulário e, sem login válido, interrompe o script aqui (st.stop)."""
    st.title('Eficiência dos eventos')
    usuarios = usuarios_cadastrados()
    if not usuarios:
        st.error('Nenhum usuário cadastrado. Crie o arquivo `.streamlit/secrets.toml` seguindo o '
                 '`secrets.toml.example` e cadastre os usuários com `python auth.py`.')
        st.stop()

    with st.form('login'):
        login = st.text_input('Usuário').strip()
        senha = st.text_input('Senha', type='password')
        entrar = st.form_submit_button('Entrar', type='primary')
    if entrar:
        cadastro = usuarios.get(login)
        # mesma mensagem para usuário inexistente e senha errada: não revela quais logins existem
        if cadastro and auth.conferir_senha(senha, cadastro.get('senha_hash', '')):
            st.session_state['usuario'] = login
            st.session_state['perfil'] = cadastro.get('perfil', 'leitor')
            st.rerun()
        st.error('Usuário ou senha incorretos.')
    st.stop()


if 'usuario' not in st.session_state:
    tela_de_login()                         # sem login, nada abaixo desta linha é executado

usuario_logado = st.session_state['usuario']
eh_tecnico = st.session_state['perfil'] == 'tecnico'


# ======================================================================= dados
def ler_planilha(conteudo: bytes, nome: str) -> pd.DataFrame:
    if nome.lower().endswith('.csv'):
        return pd.read_csv(io.BytesIO(conteudo))
    return pd.read_excel(io.BytesIO(conteudo))


@st.cache_data(show_spinner='Rodando o DEA...')
def processar(conteudo: bytes, nome: str, orientacao: str, exclusoes: tuple) -> dict:
    """Pipeline completo, em cache: só recalcula quando a planilha ou as opções mudam."""
    bruto = ler_planilha(conteudo, nome)
    motivos = {e: 'Excluído manualmente no painel' for e in exclusoes}
    return dea.pipeline(bruto, orientacao=orientacao, exclusoes=motivos)


def planilha_publicada():
    arquivos = sorted(PASTA_PUBLICADA.glob('planilha_atual.*'))
    return arquivos[0] if arquivos else None


def fonte_em_uso():
    """Devolve (bytes, nome do arquivo, descrição) da planilha que o painel deve usar."""
    if 'upload' in st.session_state:
        u = st.session_state['upload']
        return u['conteudo'], u['nome'], f"Planilha enviada nesta sessão: **{u['nome']}**"
    publicada = planilha_publicada()
    if publicada:
        data = datetime.datetime.fromtimestamp(publicada.stat().st_mtime)
        return publicada.read_bytes(), publicada.name, f"Base publicada pelo técnico em **{data:%d/%m/%Y %H:%M}**"
    return PLANILHA_ORIGINAL.read_bytes(), PLANILHA_ORIGINAL.name, 'Base original (EDA_QN)'


# ======================================================================= barra lateral
with st.sidebar:
    st.caption(f"Conectado como **{usuario_logado}** ({'técnico' if eh_tecnico else 'leitor'})")
    if st.button('Sair', width='stretch'):
        st.session_state.clear()            # apaga login, perfil e planilha da sessão
        st.rerun()

    if 'aviso' in st.session_state:          # mensagem guardada antes do st.rerun()
        st.success(st.session_state.pop('aviso'))

    st.header('Dados')
    conteudo, nome_arquivo, descricao = fonte_em_uso()
    st.caption(descricao)

    if eh_tecnico:                          # leitores não veem a área de atualização
        with st.expander('Área do técnico: atualizar planilha'):
            arquivo = st.file_uploader('Planilha atualizada (.csv ou .xlsx)', type=['csv', 'xlsx'])
            if arquivo is not None:
                novo = arquivo.getvalue()
                try:
                    faltando = dea.validar_planilha(dea.preparar(ler_planilha(novo, arquivo.name)))
                except Exception as erro:
                    faltando, novo = None, None
                    st.error(f'Não consegui ler o arquivo: {erro}')
                if faltando:
                    st.error('A planilha não tem as colunas obrigatórias:\n\n' + '\n'.join(f'- {c}' for c in faltando))
                elif novo is not None:
                    if st.button('Testar nesta sessão', width='stretch',
                                 help='Só você vê o resultado. Bom para conferir antes de publicar.'):
                        st.session_state['upload'] = {'conteudo': novo, 'nome': arquivo.name}
                        st.rerun()
                    if st.button('Publicar como base oficial', type='primary', width='stretch',
                                 help='Substitui a base que todos os usuários veem.'):
                        PASTA_PUBLICADA.mkdir(exist_ok=True)
                        for antigo in PASTA_PUBLICADA.glob('planilha_atual.*'):
                            antigo.unlink()
                        (PASTA_PUBLICADA / f'planilha_atual{Path(arquivo.name).suffix.lower()}').write_bytes(novo)
                        st.session_state.pop('upload', None)
                        st.session_state['aviso'] = 'Base publicada. O painel foi atualizado para todos.'
                        st.cache_data.clear()
                        st.rerun()
            if 'upload' in st.session_state and st.button('Voltar para a base publicada', width='stretch'):
                st.session_state.pop('upload')
                st.rerun()

    st.header('Opções do modelo')
    orientacao = st.radio(
        'Pergunta do modelo', list(dea.ORIENTACOES), format_func=dea.ORIENTACOES.get,
        help='Insumo: mantém a receita e procura o menor custo possível. Output: mantém os custos e procura '
             'a maior receita possível. Use output quando os custos têm piso (ex.: cachê mínimo de atração).')
    eventos_planilha = dea.preparar(ler_planilha(conteudo, nome_arquivo))[dea.COL_ID].dropna().tolist()
    exclusoes = st.multiselect(
        'Eventos fora da análise', options=sorted(eventos_planilha, key=lambda e: (len(e), e)),
        help='Eventos com valor vazio, zero ou negativo em algum input/output já ficam fora automaticamente.')

try:
    saida = processar(conteudo, nome_arquivo, orientacao, tuple(sorted(exclusoes)))
except ValueError as erro:
    st.error(str(erro))
    st.stop()

eventos = saida['eventos']
resultado = saida['resultado']
cooper = saida['cooper']
eh_input = orientacao == 'in'


def mostrar(fig):
    """Padrão brasileiro nos números (1.234,5) e largura total."""
    fig.update_layout(separators=',.')
    st.plotly_chart(fig, width='stretch')


def brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(',', '.')


def brl_curto(valor: float) -> str:
    """R$ 275,8 mil / R$ 2,3 mi: cabe nos cartões de métrica."""
    if abs(valor) >= 1e6:
        return f"R$ {num(valor / 1e6, 1)} mi"
    if abs(valor) >= 1e3:
        return f"R$ {num(valor / 1e3, 1)} mil"
    return brl(valor)


def num(valor: float, casas: int = 3) -> str:
    """Número com vírgula decimal (0,763)."""
    return f"{valor:.{casas}f}".replace('.', ',')


# coluna de "quanto se ganha" conforme a pergunta do modelo
COL_GANHO, COL_GANHO_PCT = ('economia_potencial', 'economia_%') if eh_input else ('ganho_receita', 'ganho_%')
NOME_GANHO = 'Economia potencial' if eh_input else 'Receita adicional possível'


# ======================================================================= cabeçalho
st.title('Eficiência dos eventos')
st.caption(f"Data Envelopment Analysis (DEA) · orientação a **{'insumo' if eh_input else 'output'}** · inputs: "
           'estrutura + equipe, atrações e insumos · output: receita total (bar + bilheteria)')
if not cooper['ok']:
    st.warning(f"Só {cooper['n']} eventos na análise: a regra de Cooper pede pelo menos {cooper['minimo']} "
               'para 3 inputs e 1 output. Os scores ficam pouco confiáveis (muitos eventos saem eficientes).')

aba_geral, aba_ficha, aba_escala, aba_atracoes, aba_metodo = st.tabs(
    ['Visão geral', 'Ficha do evento', 'Gestão × escala', 'Atrações', 'Metodologia'])


# ======================================================================= 1. visão geral
with aba_geral:
    comp = resultado['comparacao'].copy()
    comp['ganho_bcc'] = comp['evento'].map(resultado['bcc'].set_index('evento')[COL_GANHO])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Eventos analisados', len(comp))
    c2.metric('Eficientes (CCR)', f"{(comp['CCR'] >= 0.999).sum()} de {len(comp)}")
    c3.metric(f'{NOME_GANHO} (CCR)', brl_curto(comp[COL_GANHO].sum()),
              help='CCR: soma do que cada evento ganharia se operasse como os melhores, em qualquer tamanho. '
                   'É o teto teórico.')
    c4.metric(f'{NOME_GANHO} (BCC)', brl_curto(comp['ganho_bcc'].sum()),
              help='BCC: o que dá para ganhar só com gestão, sem mudar o tamanho do evento. É o valor realista.')

    ranking = comp.sort_values('CCR')
    fig = px.bar(ranking, x='CCR', y='evento', orientation='h', color='problema_principal',
                 color_discrete_map=CORES, category_orders={'problema_principal': list(CORES)},
                 custom_data=['BCC', 'escala', 'retorno', COL_GANHO],
                 labels={'problema_principal': 'Diagnóstico', 'evento': '', 'CCR': 'Eficiência global (CCR)'})
    fig.update_traces(hovertemplate='<b>%{y}</b><br>CCR: %{x:.3f}<br>BCC: %{customdata[0]:.3f}'
                                    '<br>Escala: %{customdata[1]:.3f} (%{customdata[2]})'
                                    f'<br>{NOME_GANHO}: R$ %{{customdata[3]:,.0f}}<extra></extra>',
                      marker_line_width=0)
    fig.update_yaxes(categoryorder='array', categoryarray=ranking['evento'].tolist())
    fig.update_layout(title='Ranking de eficiência', height=max(320, 28 * len(ranking)),
                      xaxis_range=[0, 1.02], legend_title_text='Diagnóstico', bargap=0.25,
                      margin=dict(l=0, r=10, t=50, b=10))
    mostrar(fig)

    ganhos = comp[comp[COL_GANHO] > 0].sort_values(COL_GANHO)
    if len(ganhos):
        fig = px.bar(ganhos, x=COL_GANHO, y='evento', orientation='h', color='problema_principal',
                     color_discrete_map=CORES, category_orders={'problema_principal': list(CORES)},
                     custom_data=[COL_GANHO_PCT],
                     labels={COL_GANHO: 'R$ por evento', 'evento': '', 'problema_principal': 'Diagnóstico'})
        base = 'do custo' if eh_input else 'da receita'
        fig.update_traces(hovertemplate=f'<b>%{{y}}</b><br>R$ %{{x:,.0f}} (%{{customdata[0]}}% {base})<extra></extra>',
                          marker_line_width=0)
        fig.update_yaxes(categoryorder='array', categoryarray=ganhos['evento'].tolist())
        fig.update_xaxes(tickformat=',.0f', tickprefix='R$ ')
        fig.update_layout(title=f'Onde está o dinheiro: {NOME_GANHO.lower()} por evento (CCR)',
                          height=max(260, 30 * len(ganhos)), bargap=0.25, margin=dict(l=0, r=10, t=50, b=10))
        mostrar(fig)

    st.subheader('Tabela completa')
    st.dataframe(
        comp[['evento', 'CCR', 'BCC', 'escala', 'retorno', 'problema_principal', 'bcc_por_extremo',
              'custo_atual', 'receita_atual', COL_GANHO, COL_GANHO_PCT, 'ganho_bcc']],
        hide_index=True, width='stretch',
        column_config={
            'evento': 'Evento', 'retorno': 'Retorno de escala', 'problema_principal': 'Diagnóstico',
            'CCR': st.column_config.NumberColumn('CCR', format='localized'),
            'BCC': st.column_config.NumberColumn('BCC', format='localized'),
            'escala': st.column_config.NumberColumn('Escala', format='localized'),
            'bcc_por_extremo': st.column_config.CheckboxColumn(
                'BCC = 1 por ser extremo?', help='O evento tem o menor valor da base em algum custo ou na receita. '
                                                 'No BCC isso garante score 1 quase automaticamente (não há evento '
                                                 'menor para comparar). Ler com cuidado.'),
            'custo_atual': st.column_config.NumberColumn('Custo atual (R$)', format='localized'),
            'receita_atual': st.column_config.NumberColumn('Receita atual (R$)', format='localized'),
            COL_GANHO: st.column_config.NumberColumn(f'{NOME_GANHO} CCR (R$)', format='localized'),
            COL_GANHO_PCT: st.column_config.NumberColumn(f'{NOME_GANHO} CCR (%)', format='localized'),
            'ganho_bcc': st.column_config.NumberColumn(f'{NOME_GANHO} BCC (R$)', format='localized'),
        })


# ======================================================================= 2. ficha do evento
def recomendacao(linha, tabela_bcc) -> str:
    diag, ret, esc = linha['problema_principal'], linha['retorno'], linha['escala']
    if diag == 'Eficiente':
        return ('**Referência.** Gera o máximo de receita para os custos que tem e está no tamanho ideal. '
                'As práticas deste evento servem de modelo para os outros.')
    if diag == 'Escala':
        texto = (f"**Gestão boa para o porte, problema de tamanho.** A eficiência de gestão (BCC) é "
                 f"{num(linha['BCC'])}; a perda vem da escala ({num(esc)}). ")
        if ret == 'Crescente':
            texto += ('O evento é **pequeno demais para a estrutura de custos que tem**: parte dos custos (estrutura, '
                      'atrações) é quase fixa. Mais público ou uma estrutura proporcional ao público esperado tendem '
                      'a aumentar a eficiência.')
        else:
            texto += ('O evento **já passou do tamanho ideal**: crescer tende a piorar a eficiência; '
                      'antes, vale aproveitar melhor a estrutura atual.')
        return texto
    # só folgas relevantes: abaixo de R$ 100 ou 0,5% do input é ruído do solver
    folgas = {dea.ROTULOS_INPUTS[n]: tabela_bcc[f'folga_{n}'] for n in dea.NOMES_INPUTS
              if tabela_bcc[f'folga_{n}'] > max(100, 0.005 * tabela_bcc[f'atual_{n}'])}
    if eh_input:
        texto = (f"**Tamanho adequado, problema de gestão.** Comparado a eventos de porte parecido, poderia gerar a "
                 f"mesma receita com {linha['BCC'] * 100:.0f}% dos custos. ")
    else:
        texto = (f"**Tamanho adequado, problema de gestão.** Comparado a eventos de porte parecido, com os mesmos "
                 f"custos poderia faturar {(1 / linha['BCC'] - 1) * 100:.0f}% a mais. ")
    if folgas:
        maior = max(folgas, key=folgas.get)
        texto += f'O excesso mais concentrado está em **{maior.lower()}** ({brl(folgas[maior])} além do corte proporcional). '
    texto += 'O caminho é se espelhar nos eventos de referência (peers).'
    return texto


with aba_ficha:
    no_dea = eventos[eventos['motivo_exclusao'] == '']
    lista = sorted(no_dea[dea.COL_ID], key=lambda e: (len(e), e))
    col_a, col_b = st.columns([2, 1])
    evento = col_a.selectbox('Evento', lista)
    modelo = col_b.radio('Metas pelo modelo', ['CCR', 'BCC'], horizontal=True,
                         help='CCR: compara com todos os eventos. BCC: só com eventos de porte parecido.')
    linha = resultado['comparacao'].set_index('evento').loc[evento]
    tabela_modelo = resultado[modelo.lower()].set_index('evento').loc[evento]
    dados_evento = no_dea.set_index(dea.COL_ID).loc[evento]

    st.subheader(f"{evento} · público de {dados_evento['Publico']:,.0f} pessoas".replace(',', '.'))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Eficiência global (CCR)', num(linha['CCR']))
    m2.metric('Eficiência de gestão (BCC)', num(linha['BCC']))
    m3.metric('Eficiência de escala', num(linha['escala']), help=f"Retorno de escala: {linha['retorno']}")
    m4.metric(f'{NOME_GANHO} ({modelo})', brl_curto(tabela_modelo[COL_GANHO]),
              delta=f"{'-' if eh_input else '+'}{num(tabela_modelo[COL_GANHO_PCT], 1)}% "
                    f"{'do custo' if eh_input else 'de receita'}", delta_color='off')
    st.info(recomendacao(linha, resultado['bcc'].set_index('evento').loc[evento]))
    if linha['bcc_por_extremo']:
        st.warning(f"**Atenção ao BCC = 1.** Este evento tem a {linha['extremo_em']} da base. No BCC, isso dá score 1 "
                   'quase automaticamente, porque não existe evento menor para compará-lo, e não necessariamente por '
                   'boa gestão. Olhe o CCR e a escala.')

    if eh_input:
        metas = pd.DataFrame([
            {'Item': dea.ROTULOS_INPUTS[n], 'Série': serie, 'R$': tabela_modelo[f'{prefixo}_{n}']}
            for n in dea.NOMES_INPUTS for serie, prefixo in [('Atual', 'atual'), ('Meta', 'meta')]])
        titulo = f'Custo atual × meta por input ({modelo})'
    else:
        metas = pd.DataFrame([{'Item': 'Receita total', 'Série': 'Atual', 'R$': tabela_modelo['receita_atual']},
                              {'Item': 'Receita total', 'Série': 'Meta', 'R$': tabela_modelo['receita_meta']}])
        titulo = f'Receita atual × meta ({modelo})'
    fig = px.bar(metas, x='Item', y='R$', color='Série', barmode='group', color_discrete_map=CORES_SERIE,
                 labels={'Item': ''})
    fig.update_traces(hovertemplate='%{x}<br>R$ %{y:,.0f}<extra>%{fullData.name}</extra>', marker_line_width=0)
    fig.update_yaxes(tickformat=',.0f', tickprefix='R$ ')
    fig.update_layout(title=titulo, bargap=0.3, bargroupgap=0.08, legend_title_text='',
                      margin=dict(l=0, r=10, t=50, b=10))
    mostrar(fig)
    if eh_input:
        st.caption('A meta do DEA é matemática: ela não sabe que alguns custos têm piso (ex.: cachê mínimo de '
                   'atração). Se o corte sugerido for inviável, veja a pergunta "Output" na barra lateral.')

    col_p, col_f = st.columns(2)
    with col_p:
        st.markdown('**Peers (eventos de referência)**')
        peers = tabela_modelo['peers_pesos']
        if list(peers) == [evento]:
            st.write('É a própria referência.')
        else:
            st.dataframe(pd.DataFrame({'Peer': list(peers), 'Peso (λ)': list(peers.values())}),
                         hide_index=True, width='stretch',
                         column_config={'Peso (λ)': st.column_config.NumberColumn(format='localized')})
            st.caption('O peso diz quanto de cada peer compõe o evento-modelo da comparação.')
    with col_f:
        st.markdown('**Redução sugerida por input**' if eh_input else '**Folga por input** (excesso além do necessário)')
        st.dataframe(pd.DataFrame({
            'Input': [dea.ROTULOS_INPUTS[n] for n in dea.NOMES_INPUTS],
            'Atual (R$)': [tabela_modelo[f'atual_{n}'] for n in dea.NOMES_INPUTS],
            'Redução (%)': [tabela_modelo[f'reducao_%_{n}'] for n in dea.NOMES_INPUTS],
            'Folga extra (R$)': [tabela_modelo[f'folga_{n}'] if tabela_modelo[f'folga_{n}'] > 100 else 0
                                 for n in dea.NOMES_INPUTS],
        }), hide_index=True, width='stretch',
            column_config={
                'Atual (R$)': st.column_config.NumberColumn(format='localized'),
                'Redução (%)': st.column_config.NumberColumn(format='localized'),
                'Folga extra (R$)': st.column_config.NumberColumn(
                    format='localized', help='Excesso além do corte proporcional, só neste input.')})


# ======================================================================= 3. gestão x escala
with aba_escala:
    comp = resultado['comparacao']
    fig = px.scatter(comp, x='escala', y='BCC', color='problema_principal', size='custo_atual', size_max=38,
                     color_discrete_map=CORES, category_orders={'problema_principal': list(CORES)},
                     hover_name='evento', custom_data=['CCR', 'retorno', COL_GANHO],
                     labels={'escala': 'Eficiência de escala (tamanho)', 'BCC': 'Eficiência de gestão (BCC)',
                             'problema_principal': 'Diagnóstico'})
    fig.update_traces(hovertemplate='<b>%{hovertext}</b><br>Gestão (BCC): %{y:.3f}<br>Escala: %{x:.3f} '
                                    '(%{customdata[1]})<br>CCR: %{customdata[0]:.3f}<br>'
                                    f'{NOME_GANHO}: R$ %{{customdata[2]:,.0f}}<extra></extra>',
                      marker=dict(line=dict(width=2, color='white'), opacity=0.85))
    minimo = min(comp['escala'].min(), comp['BCC'].min()) - 0.03
    fig.update_layout(xaxis_range=[minimo, 1.01], yaxis_range=[minimo, 1.02], height=560,
                      margin=dict(l=0, r=10, t=30, b=10))
    mostrar(fig)
    n_eficientes = int((comp['CCR'] >= 0.999).sum())
    contagem = comp['retorno'].value_counts()
    st.markdown(
        f'- **Canto superior direito (1; 1):** eficientes ({n_eficientes} eventos, sobrepostos no mesmo ponto).\n'
        '- **Embaixo à direita:** tamanho certo, mas desperdiça recurso → melhorar a gestão.\n'
        '- **Em cima à esquerda:** gestão boa, mas o tamanho não é o ideal → ver o retorno de escala '
        '(crescente = pequeno demais; decrescente = grande demais).\n'
        '- O tamanho do círculo é o custo total do evento.\n'
        f"- **Retorno de escala nesta base:** {contagem.get('Crescente', 0)} crescente, "
        f"{contagem.get('Constante', 0)} constante, {contagem.get('Decrescente', 0)} decrescente.")


# ======================================================================= 4. atrações
with aba_atracoes:
    st.markdown('O custo de atração se comporta como **custo fixo**: varia pouco entre eventos e tem um piso '
                '(nenhuma atração toca por qualquer valor). Por isso, a pergunta útil não é "quanto cortar do cachê", '
                'e sim **"a atração trouxe público que justifique o cachê?"**. O indicador abaixo responde isso.')
    atr = no_dea[[dea.COL_ID, 'Custo_Atracoes', 'Publico', 'atracao_por_pessoa', 'receita_por_pessoa']].copy()
    mediana_cache = atr['Custo_Atracoes'].median()
    mediana_pp = atr['atracao_por_pessoa'].median()
    atr['situacao'] = 'Dentro do esperado'
    atr.loc[(atr['atracao_por_pessoa'] > mediana_pp) & (atr['Custo_Atracoes'] > mediana_cache),
            'situacao'] = 'Cachê alto, pouco público'
    atr.loc[(atr['atracao_por_pessoa'] > mediana_pp) & (atr['Custo_Atracoes'] <= mediana_cache),
            'situacao'] = 'Cachê baixo, evento pequeno'

    a1, a2, a3 = st.columns(3)
    a1.metric('Cachê mediano', brl(mediana_cache))
    a2.metric('Atração por pessoa (mediana)', f"R$ {num(mediana_pp, 2)}")
    a3.metric('Faixa do cachê', f"{brl(atr['Custo_Atracoes'].min())} a {brl(atr['Custo_Atracoes'].max())}")

    ordem = atr.sort_values('atracao_por_pessoa')
    fig = px.bar(ordem, x='atracao_por_pessoa', y=dea.COL_ID, orientation='h',
                 custom_data=['Custo_Atracoes', 'Publico', 'situacao'],
                 labels={'atracao_por_pessoa': 'R$ de atração por pessoa', dea.COL_ID: ''})
    fig.update_traces(marker_color=COR_UNICA, marker_line_width=0,
                      hovertemplate='<b>%{y}</b><br>R$ %{x:.2f} por pessoa<br>Cachê: R$ %{customdata[0]:,.0f}'
                                    '<br>Público: %{customdata[1]:,.0f}<br>%{customdata[2]}<extra></extra>')
    fig.add_vline(x=mediana_pp, line_dash='dash', line_color='#7a7974', annotation_text='mediana')
    fig.update_yaxes(categoryorder='array', categoryarray=ordem[dea.COL_ID].tolist())
    fig.update_layout(title='Custo de atração por pessoa (menor = atração que "se pagou" em público)',
                      height=max(320, 26 * len(ordem)), bargap=0.25, margin=dict(l=0, r=10, t=50, b=10))
    mostrar(fig)

    fig = px.scatter(atr, x='Publico', y='Custo_Atracoes', hover_name=dea.COL_ID,
                     custom_data=['atracao_por_pessoa', 'situacao'],
                     labels={'Publico': 'Público (pessoas)', 'Custo_Atracoes': 'Cachê das atrações (R$)'})
    fig.update_traces(marker=dict(color=COR_UNICA, size=11, line=dict(width=2, color='white')),
                      hovertemplate='<b>%{hovertext}</b><br>Público: %{x:,.0f}<br>Cachê: R$ %{y:,.0f}'
                                    '<br>R$ %{customdata[0]:.2f} por pessoa<br>%{customdata[1]}<extra></extra>')
    fig.update_yaxes(tickformat=',.0f', tickprefix='R$ ')
    fig.update_layout(title='Cachê × público: o cachê quase não acompanha o tamanho do evento', height=420,
                      margin=dict(l=0, r=10, t=50, b=10))
    mostrar(fig)

    st.markdown('**Como ler**\n'
                '- **Cachê alto, pouco público:** a escolha da atração é o problema: ela custou caro e não trouxe gente.\n'
                '- **Cachê baixo, evento pequeno:** não há o que cortar no cachê; o problema é o tamanho do evento (escala).\n'
                '- Cachê alto não é ruim quando o evento lota: o que importa é o R$ por pessoa, não o cachê sozinho.')
    st.dataframe(
        atr.sort_values('atracao_por_pessoa', ascending=False),
        hide_index=True, width='stretch',
        column_config={
            dea.COL_ID: 'Evento', 'situacao': 'Situação',
            'Custo_Atracoes': st.column_config.NumberColumn('Cachê (R$)', format='localized'),
            'Publico': st.column_config.NumberColumn('Público', format='localized'),
            'atracao_por_pessoa': st.column_config.NumberColumn('Atração por pessoa (R$)', format='%.2f'),
            'receita_por_pessoa': st.column_config.NumberColumn('Receita por pessoa (R$)', format='%.2f'),
        })


# ======================================================================= 5. metodologia
with aba_metodo:
    st.header('Como o painel calcula')
    if eh_input:
        pergunta = 'mantendo a receita, quanto cada evento poderia gastar a menos se operasse como os melhores eventos?'
    else:
        pergunta = 'mantendo os custos, quanto cada evento poderia faturar a mais se operasse como os melhores eventos?'
    st.markdown(f"""
**Pergunta (orientação a {'insumo' if eh_input else 'output'}):** {pergunta}

**Variáveis**
- **Inputs (R$ por evento):** estrutura + equipe, atrações e insumos. Cada real de custo entra uma vez só.
- **Output (R$ por evento):** receita total = receita do bar + receita da bilheteria.

**Modelos**
- **CCR** (retornos constantes) mede a eficiência global: gestão + tamanho.
- **BCC** (retornos variáveis) compara só eventos de porte parecido e mede a gestão.
- **Escala = CCR ÷ BCC**; o modelo **RNC** indica se o evento é pequeno (retorno crescente) ou grande demais (decrescente).
- Os scores vão de 0 a 1 nas duas orientações. A output, o Pyfrontier calcula φ ≥ 1 ("poderia faturar φ vezes mais")
  e o painel mostra 1/φ. No CCR, o score é o mesmo nas duas orientações; no BCC, pode mudar.

**Escolhas de modelagem**
- **Receita, e não lucro, como output:** o lucro pode ser negativo (o DEA exige valores positivos) e já desconta
  os custos, que estão nos inputs; o custo seria contado duas vezes.
- **Tickets médios não são inputs:** são preço por pessoa, não recurso gasto. A orientação a insumo mandaria
  "baixar o preço", o que não faz sentido, e a receita já é ticket × público.
- **Público não é input nem output:** é o que liga os custos à receita; aparece nos indicadores por pessoa.

**Como ler o ganho potencial:** a meta é o que os eventos de referência (peers) mostram ser possível, não uma
previsão garantida. A economia/ganho CCR é o teto teórico; o BCC é o valor alcançável sem mudar o tamanho do evento.
""")

    st.subheader('Quantidade de eventos (regra de Cooper)')
    st.write(f"{cooper['n']} eventos para 3 inputs e 1 output: mínimo recomendado max{{3 × 1, 3 × (3 + 1)}} = "
             f"{cooper['minimo']} {'✅' if cooper['ok'] else '❌ poucos eventos'}")

    st.subheader('Eventos fora da análise')
    fora = eventos.loc[eventos['motivo_exclusao'] != '', [dea.COL_ID, 'motivo_exclusao']]
    if len(fora):
        st.dataframe(fora.rename(columns={dea.COL_ID: 'Evento', 'motivo_exclusao': 'Motivo'}),
                     hide_index=True, width='stretch')
    else:
        st.write('Nenhum.')

    if 'diferenca_lucro' in eventos.columns:
        st.subheader('Conferência do lucro')
        dif = eventos[[dea.COL_ID, 'Receita_Total', 'Custo_Total', 'Lucro', 'diferenca_lucro']].copy()
        dif['dif_%'] = (dif['diferenca_lucro'] / dif['Receita_Total'] * 100).round(1)
        st.markdown('Lucro informado na planilha × receita total − os custos do modelo. A diferença indica receitas '
                    'ou custos que **não estão na planilha**. Positiva: algum custo faltando (taxas de cartão, de '
                    'ingresso, impostos). Negativa: alguma receita faltando (ex.: patrocínio).')
        st.dataframe(dif.sort_values('dif_%', ascending=False), hide_index=True, width='stretch',
                     column_config={
                         dea.COL_ID: 'Evento',
                         'Receita_Total': st.column_config.NumberColumn('Receita (R$)', format='localized'),
                         'Custo_Total': st.column_config.NumberColumn('Custos do modelo (R$)', format='localized'),
                         'Lucro': st.column_config.NumberColumn('Lucro informado (R$)', format='localized'),
                         'diferenca_lucro': st.column_config.NumberColumn('Diferença (R$)', format='localized'),
                         'dif_%': st.column_config.NumberColumn('Diferença (% da receita)', format='localized'),
                     })

    st.subheader('Limitações')
    st.markdown("""
- **Eficiência relativa:** score 1,000 significa "o melhor desta base", não "perfeito".
- **Custos com piso:** o DEA trata todo custo como redutível. Metas de corte em atrações podem ser inviáveis
  (cachê mínimo); nesse caso, a pergunta "Output" é a leitura mais útil.
- **BCC = 1 em eventos extremos:** quem tem o menor valor da base em algum custo ou na receita sai eficiente no BCC
  quase automaticamente ("eficiente por falta de comparação"). Esses casos aparecem marcados na tabela.
- **Receitas e custos fora do modelo:** o lucro informado não bate exatamente com receita − custos (ver conferência
  acima). As diferenças são pequenas, mas favorecem levemente os eventos grandes.
- **Poucos eventos e inputs correlacionados:** com cerca de 20 eventos, cada um pesa muito no resultado, e um valor
  errado pode virar referência e mudar o score de todos.
""")
