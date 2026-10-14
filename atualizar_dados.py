#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atualizar_dados.py — Diagnóstico da Educação Escolar Quilombola · ENFMQ (CONAQ)
================================================================================

Gera o painel (index.html) a partir das respostas do formulário "Diagnóstico da
Educação Escolar Quilombola – ENFMQ", lidas da planilha do Google publicada como
CSV. Roda todo dia sozinho no GitHub Actions (ver .github/workflows/atualizar.yml),
mas também pode ser rodado à mão.

Uso (requer só Python 3.9+, nada para instalar):

    # lendo direto da planilha publicada (é o que o GitHub faz todo dia)
    PLANILHA_CSV_URL="https://docs.google.com/.../pub?gid=...&output=csv" python3 atualizar_dados.py

    # ou lendo um CSV baixado à mão (Arquivo → Fazer download → .csv)
    python3 atualizar_dados.py --arquivo respostas.csv

Outras opções:
    --url URL          o link do CSV publicado (alternativa à variável de ambiente)
    --saida pagina.html  grava com outro nome (padrão: index.html)

--------------------------------------------------------------------------------
POR QUE O LINK DA PLANILHA NÃO ESTÁ ESCRITO AQUI
--------------------------------------------------------------------------------
A planilha de respostas tem nome, e-mail e data de nascimento de estudantes,
muitas menores de idade. Um link "publicado na web" do Google abre para qualquer
pessoa que o tenha, sem login. Se ele ficasse escrito neste arquivo, e o
repositório for público, qualquer um que lesse o código chegaria aos dados
pessoais. Por isso o link fica guardado como SEGREDO do GitHub
(Settings → Secrets and variables → Actions → PLANILHA_CSV_URL) e o script o
recebe pela variável de ambiente PLANILHA_CSV_URL.

--------------------------------------------------------------------------------
O QUE ESTE SCRIPT FAZ COM OS DADOS PESSOAIS
--------------------------------------------------------------------------------
A página é pública. Então o script decide, coluna por coluna, o que sai:

  NUNCA saem       nome, e-mail, data de nascimento, horário de envio, nome da
                   escola, município de cada pessoa, tipo de deficiência, motivo
                   de abandono, monitora pedagógica e todas as respostas abertas.
  saem RESUMIDAS   data de nascimento → faixa etária; horário de envio → total
                   de respostas por dia; município → contagem por município no
                   mapa (sem ligação com as respostas); deficiência e abandono →
                   só o total nacional.
  saem por pessoa  as respostas fechadas (de escolha), sem nada que identifique
                   quem respondeu, para alimentar filtros e cruzamentos.

E há uma segunda proteção: nas variáveis que ajudam a reconhecer alguém (UF,
gênero, raça/cor, faixa etária, série e turno), categorias com menos de
MINIMO_GRUPO pessoas são agrupadas. Ver agrupa_grupos_pequenos().
"""

import argparse
import csv
import difflib
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, OrderedDict
from datetime import datetime

# ----------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------
TEMPLATE_PATH = "template.html"
SAIDA_PADRAO = "index.html"

MUNICIPIOS_URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"
MUNICIPIOS_CACHE = "municipios-ibge.csv"   # fica no repositório: o GitHub não precisa baixar de novo

# Trava contra download que falhou pela metade ou planilha errada: se vierem
# menos respostas do que isto, o index.html antigo NÃO é sobrescrito.
MINIMO_RESPOSTAS = 30

# Proteção de anonimato: categorias com menos pessoas do que isto são agrupadas
# nas variáveis que ajudam a reconhecer alguém. 5 é o piso usual em estatística
# pública (o IBGE e o INEP usam regras parecidas para não divulgar células pequenas).
MINIMO_GRUPO = 5

UF_NOMES = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia', 'CE': 'Ceará',
    'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão',
    'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais', 'PA': 'Pará',
    'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco', 'PI': 'Piauí', 'RJ': 'Rio de Janeiro',
    'RN': 'Rio Grande do Norte', 'RS': 'Rio Grande do Sul', 'RO': 'Rondônia', 'RR': 'Roraima',
    'SC': 'Santa Catarina', 'SP': 'São Paulo', 'SE': 'Sergipe', 'TO': 'Tocantins'}
UF_REGIAO = {
    'AC': 'Norte', 'AP': 'Norte', 'AM': 'Norte', 'PA': 'Norte', 'RO': 'Norte', 'RR': 'Norte', 'TO': 'Norte',
    'AL': 'Nordeste', 'BA': 'Nordeste', 'CE': 'Nordeste', 'MA': 'Nordeste', 'PB': 'Nordeste',
    'PE': 'Nordeste', 'PI': 'Nordeste', 'RN': 'Nordeste', 'SE': 'Nordeste',
    'DF': 'Centro-Oeste', 'GO': 'Centro-Oeste', 'MT': 'Centro-Oeste', 'MS': 'Centro-Oeste',
    'ES': 'Sudeste', 'MG': 'Sudeste', 'RJ': 'Sudeste', 'SP': 'Sudeste',
    'PR': 'Sul', 'RS': 'Sul', 'SC': 'Sul'}
# código IBGE da UF (2 primeiros dígitos do código do município) -> sigla
UF_CODIGO = {'11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP', '17': 'TO',
             '21': 'MA', '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL',
             '28': 'SE', '29': 'BA', '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP', '41': 'PR',
             '42': 'SC', '43': 'RS', '50': 'MS', '51': 'MT', '52': 'GO', '53': 'DF'}

# Respostas de município que não contêm o nome do município, só o da comunidade.
# Chave: (UF, trecho do texto sem acento e em minúsculas). Valor: município.
# Quando o log avisar "município não identificado", é aqui que se acrescenta.
MUNICIPIO_APELIDOS = {
    ('BA', 'santiago do iguape'): 'Cachoeira',
    ('BA', 'ferias de santana'): 'Feira de Santana',
    ('PR', 'corrego das mocas'): 'Adrianópolis',
    ('PR', 'porto velho'): 'Adrianópolis',        # Quilombo Porto Velho, Vale do Ribeira paranaense
    ('TO', 'baiao'): 'Almas',                     # Comunidade Quilombola Baião
    ('TO', 'alams'): 'Almas',                     # erro de digitação
}

# ----------------------------------------------------------------------
# AS PERGUNTAS
# ----------------------------------------------------------------------
# Cada pergunta do formulário que vai para o painel está descrita aqui. O script
# acha a coluna pelo trecho em 'acha' (sem acento, sem maiúscula), e não pelo
# número da pergunta: assim, se alguém renumerar o formulário, nada quebra.
# Quando 'acha' começa com '^', é uma expressão regular sobre o cabeçalho inteiro.
#
#   tipo   'unica'    uma resposta por pessoa
#          'escala'   nota numérica (de 'min' a 'max')
#          'multipla' caixas de seleção: a pessoa pode marcar várias
#   ordem  a ordem das categorias no gráfico. Para 'unica', uma resposta fora da
#          lista vira 'Outra resposta' (é o "Outro: ___" do formulário).
#   tons   a cor de cada categoria, uma letra por categoria, na mesma ordem:
#            'P' 'p'  respostas favoráveis ao direito (verde forte, verde claro)
#            '0'      meio-termo
#            'n' 'N'  respostas desfavoráveis (terracota claro, terracota forte)
#            'q' 'm'  tons intermediários (verde médio, terracota médio), para quando
#                     há mais de duas categorias do mesmo lado
#            '?'      "não sei", "não se aplica" (cinza com textura)
#            's'      quantidade, do menos ao mais (um só tom, do claro ao escuro)
#            'c'      categoria sem polaridade (cores de identidade, em ordem fixa)
#          Uma categoria sem letra (ex.: a criada pelo agrupamento) sai cinza.
#   qi     True nas variáveis que ajudam a reconhecer alguém (ver MINIMO_GRUPO)
#   agregado  True = a variável sai só como total nacional, não pessoa a pessoa.
#          Vale para características que, somadas a UF, gênero e série, tornariam
#          uma estudante reconhecível (idade, turno) ou que são sensíveis por si
#          (trabalho remunerado). Elas aparecem no painel, mas não mudam com os
#          filtros nem entram no cruzador.
#   bloco  em que seção do painel a pergunta aparece
NS = 'Não sei informar'
NA = 'Não se aplica'
OUTRA = 'Outra resposta'

PERGUNTAS = [
    # ---------------- Quem respondeu ----------------
    dict(k='genero', acha='identidade de genero', tipo='unica', bloco='perfil', qi=True,
         rot='Identidade de gênero',
         ordem=['Feminino', 'Masculino', 'Prefiro não me identificar'], tons='ccc'),
    dict(k='raca', acha='autodeclaracao de raca', tipo='unica', bloco='perfil', qi=True,
         rot='Raça/cor (autodeclarada)',
         ordem=['Preta', 'Parda', 'Branca', 'Amarela', 'Indígena'], tons='ccccc',
         sinonimos={'Preto': 'Preta', 'Pardo': 'Parda', 'Branco': 'Branca', 'Amarelo': 'Amarela',
                    'Indigena': 'Indígena'}),
    # faixaEtaria é calculada da data de nascimento (ver faixa_etaria), não lida direto
    dict(k='faixaEtaria', acha=None, tipo='unica', bloco='perfil', agregado=True,
         rot='Faixa etária (na data da resposta)',
         ordem=['Até 14 anos', '15 a 17 anos', '18 a 20 anos', '21 anos ou mais'], tons='cccc'),
    dict(k='serie', acha='serie/ano', tipo='unica', bloco='perfil', qi=True,
         rot='Série/ano que cursa',
         ordem=['8º ano do Ensino Fundamental', '9º ano do Ensino Fundamental', '1ª série do Ensino Médio',
                '2ª série do Ensino Médio', '3ª série do Ensino Médio', 'EJA - Ensino Médio', 'Outro'],
         tons='ccccccc'),
    dict(k='turno', acha='horario que voce estuda', tipo='unica', bloco='perfil', agregado=True,
         rot='Turno em que estuda', ordem=['Manhã', 'Tarde', 'Noite', 'Período integral'], tons='cccc'),
    dict(k='trabalho', acha='trabalha ou ajuda', tipo='unica', bloco='perfil', agregado=True,
         rot='Trabalha ou ajuda a família/comunidade fora da escola',
         ordem=['Sim, ajudo nas atividades da família ou da comunidade', 'Sim, trabalho com remuneração',
                'Não', OUTRA], tons='cccc'),

    # ---------------- Território e participação ----------------
    dict(k='autodeclaraQuilombola', acha='se autodeclara quilombola', tipo='unica', bloco='territorio',
         rot='Se autodeclara quilombola', ordem=['Sim', 'Não'], tons='cc'),
    dict(k='moraComunidade', acha='mora em uma comunidade quilombola', tipo='unica', bloco='territorio',
         rot='Mora em comunidade quilombola', ordem=['Sim', 'Não'], tons='cc'),
    dict(k='reconhecidaFCP', acha='reconhecida pela fundacao palmares', tipo='unica', bloco='territorio',
         rot='Comunidade reconhecida pela Fundação Palmares', ordem=['Sim', 'Não', NS], tons='pn?'),
    dict(k='associacao', acha='reunioes da associacao', tipo='unica', bloco='territorio',
         rot='Participa das reuniões da associação da comunidade',
         ordem=['Participo regularmente', 'Participo raramente', 'Não participo', NA], tons='PnN?'),
    dict(k='conheceConaq', acha='conhece a conaq', tipo='unica', bloco='territorio',
         rot='Conhece a CONAQ', ordem=['Sim', 'Não'], tons='pn'),
    dict(k='participaConaq', acha='projeto ou coletivo da conaq', tipo='unica', bloco='territorio',
         rot='Participa de projeto ou coletivo da CONAQ',
         ordem=['Educação', 'Juventude', 'Não participo'], tons='ccn'),

    # ---------------- Escola, matrícula e transporte ----------------
    dict(k='escolaTerritorio', acha='escola em que voce estuda esta em territorio', tipo='unica',
         bloco='acesso', rot='A escola fica em território quilombola', ordem=['Sim', 'Não'], tons='cc'),
    dict(k='identificaMatricula', acha='identifica se o estudante e quilombola', tipo='unica', bloco='acesso',
         rot='A escola identifica o estudante quilombola na matrícula', ordem=['Sim', 'Não', NS], tons='pn?'),
    dict(k='reconhecidoEscola', acha='reconhecido como quilombola na sua escola', tipo='unica', bloco='acesso',
         rot='É reconhecida/o como quilombola na escola', ordem=['Sim', 'Não', NS], tons='pn?'),
    dict(k='dificuldadeTransporte', acha='dificuldades com transporte', tipo='unica', bloco='acesso',
         rot='Estudantes quilombolas têm dificuldade com o transporte escolar',
         ordem=['Não', 'Sim', NA], tons='pn?'),
    dict(k='meioTransporte', acha='meio de transporte', tipo='unica', bloco='acesso',
         rot='Meio de transporte até a escola',
         ordem=['Ônibus escolar', 'Van ou kombi escolar', 'Barco escolar', 'Transporte coletivo',
                'Transporte da família', 'A pé ou de bicicleta', 'Mais de um meio', OUTRA],
         tons='cccccccc'),
    dict(k='avaliacaoTransporte', acha='avalia o transporte', tipo='escala', bloco='acesso',
         rot='Avaliação do transporte escolar', min=1, max=5, polaridade=1,
         extremos=('pior avaliação', 'melhor avaliação')),
    dict(k='tempoTransporte', acha='tempo voce passa no transporte', tipo='unica', bloco='acesso',
         rot='Tempo de deslocamento até a escola',
         ordem=['Menos de 1 hora', 'Entre 1 e 2 horas', 'Entre 2 e 3 horas', 'Mais de 3 horas', NA, OUTRA],
         tons='p0nN??'),

    # ---------------- Estrutura da escola ----------------
    dict(k='acessibilidade', acha='acessibilidade para todos', tipo='escala', bloco='estrutura',
         rot='Acessibilidade da escola para todos os alunos', min=0, max=5, polaridade=1,
         extremos=('menos acessível', 'mais acessível')),
    dict(k='merenda', acha='qualidade da merenda', tipo='escala', bloco='estrutura',
         rot='Qualidade da merenda escolar', min=1, max=5, polaridade=1,
         extremos=('pior qualidade', 'melhor qualidade')),
    dict(k='alimentacaoLocal', acha='alimentacao escolar inclui', tipo='unica', bloco='estrutura',
         rot='A alimentação escolar usa produção quilombola do território',
         ordem=['Sim, com frequência', 'Às vezes', 'Raramente', 'Não', NS], tons='PpnN?'),
    dict(k='informatica', acha='sala de informatica', tipo='unica', bloco='estrutura',
         rot='Informática e internet para estudantes',
         ordem=['Sim, há sala de informática, computadores e internet disponíveis',
                'Há computadores e internet, mas não há sala de informática',
                'Há sala de informática e computadores, mas não há internet',
                'Há computadores, mas são poucos ou têm acesso limitado à internet',
                'Não há computadores nem acesso à internet', NS],
         curtos=['Sala, computadores e internet', 'Computadores e internet, sem sala',
                 'Sala e computadores, sem internet', 'Poucos computadores / internet limitada',
                 'Sem computadores nem internet', NS],
         tons='PpnmN?'),
    dict(k='quadra', acha='quadra ou espaco adequado', tipo='unica', bloco='estrutura',
         rot='Quadra ou espaço para esportes',
         ordem=['Sim, e está em boas condições', 'Sim, mas precisa de melhorias', 'Não'], tons='P0N'),
    dict(k='biblioteca', acha='biblioteca ou sala de leitura', tipo='unica', bloco='estrutura',
         rot='Biblioteca ou sala de leitura', ordem=['Sim', 'Não'], tons='PN'),
    dict(k='fechamento', acha='fechamento de escola, sala ou turma', tipo='unica', bloco='estrutura',
         rot='Fechamento de escola, sala ou turma nos últimos anos',
         ordem=['Não', 'Sim, fechamento de sala/turma', 'Sim, fechamento da escola', 'Sim, ambos', NS],
         tons='PnmN?'),

    # ---------------- Identidade, currículo e formação ----------------
    dict(k='materiais', acha='materiais didaticos voltados', tipo='unica', bloco='identidade',
         rot='Materiais didáticos sobre história e cultura quilombola',
         ordem=['Sim, possui materiais suficientes e são utilizados nas aulas',
                'Sim, possui materiais, mas não são utilizados nas aulas',
                'Sim, possui alguns materiais, mas são poucos', 'Não possui', NS],
         curtos=['Suficientes e usados nas aulas', 'Tem, mas não são usados', 'Poucos materiais',
                 'Não possui', NS],
         tons='P0nN?'),
    dict(k='formacaoProfessores', acha='recebem formacao sobre', tipo='unica', bloco='identidade',
         rot='Professoras/es recebem formação em Educação Escolar Quilombola', ordem=['Sim', 'Não', NS],
         tons='PN?'),
    dict(k='profQuilombolas', acha='professores/as quilombolas? quantos', tipo='unica', bloco='identidade',
         rot='Professoras/es quilombolas na escola',
         ordem=['0', '1-3', '4-7', '8-10', '11-15', 'Mais de 15', NS, NA],
         curtos=['Nenhum', '1 a 3', '4 a 7', '8 a 10', '11 a 15', 'Mais de 15', NS, NA],
         tons='ssssss??'),
    dict(k='profComunidade', acha='profissionais que sao da propria comunidade', tipo='unica', bloco='identidade',
         rot='Profissionais da própria comunidade na escola',
         ordem=['0', '1-3', '4-7', '8-10', '11-15', 'Mais de 15', NS, NA],
         curtos=['Nenhum', '1 a 3', '4 a 7', '8 a 10', '11 a 15', 'Mais de 15', NS, NA],
         tons='ssssss??'),
    dict(k='atividades', acha='atividades de valorizacao da identidade', tipo='multipla', bloco='identidade',
         rot='Atividades de valorização da identidade e cultura quilombola',
         opcoes=['Dança regional/tradicional', 'Roda de conversa com as lideranças', 'Contação de histórias',
                 'Meio ambiente', 'Pinturas', 'Oficinas de artesanatos', 'Produção de material audiovisual'],
         # respostas livres reconhecidas e agrupadas (o primeiro padrão que bater vence)
         livres=[(r'consciencia negra|datas? especia|novembro|noite cultural', 'Só em datas comemorativas'),
                 (r'\bnada\b|nenhum|nem uma|nao tem|nao ha|nao temos|nao praticam|^nao$', 'Nenhuma atividade'),
                 # "não se aplica" não diz se há ou não atividade: conta como sem resposta
                 (r'nao se aplica', None)]),
    dict(k='areas', acha='areas do conhecimento', tipo='multipla', bloco='identidade',
         rot='Áreas do conhecimento que trabalham a identidade quilombola',
         opcoes=['História', 'Arte', 'Geografia', 'Sociologia', 'Língua Portuguesa', 'Filosofia', 'Matemática',
                 'Educação Física', 'Ciências', 'Química', 'Física', 'Biologia', 'Língua Inglesa',
                 'Língua Espanhola', 'Em nenhuma das áreas']),

    # ---------------- Racismo, gênero e participação ----------------
    dict(k='antirracista', acha='educacao antirracista', tipo='unica', bloco='racismo',
         rot='A escola desenvolve educação antirracista',
         ordem=['Sempre', 'Muitas vezes', 'Às vezes', 'Raramente', 'Nunca', NS], tons='Pp0nN?'),
    dict(k='racismoFrequencia', acha='presencia situacoes de racismo', tipo='escala', bloco='racismo',
         rot='Com que frequência presencia racismo ou discriminação na escola', min=0, max=5, polaridade=-1,
         extremos=('menos frequente', 'mais frequente')),
    dict(k='igualdadeMeninas', acha='mesmas oportunidades que os meninos', tipo='escala', bloco='racismo',
         rot='Meninas quilombolas têm as mesmas oportunidades que os meninos', min=0, max=5, polaridade=1,
         extremos=('menos igualdade', 'mais igualdade')),
    dict(k='participacaoDecisoes', acha='participa das decisoes', tipo='unica', bloco='racismo',
         rot='A comunidade participa das decisões sobre a escola',
         ordem=['Sim, de forma efetiva', 'Participa parcialmente', 'Participa pouco', 'Não participa', NS],
         tons='PpnN?'),
    dict(k='peDeMeia', acha='pe de meia', tipo='unica', bloco='racismo',
         rot='Recebe o Pé-de-Meia (ensino médio)', ordem=['Sim', 'Não', 'Não conheço o programa'], tons='cc?'),

    # ---------------- Obstáculos ----------------
    dict(k='obstaculos', acha='principais obstaculos', tipo='multipla', bloco='obstaculos',
         rot='Principais obstáculos ao direito à Educação Escolar Quilombola',
         opcoes=['Falta de materiais didáticos específicos', 'Transporte escolar insuficiente ou precário',
                 'Falta de formação sobre Educação Escolar Quilombola', 'Falta de professores/as quilombolas',
                 'Falta de valorização da identidade e cultura quilombola', 'Racismo e discriminação',
                 'Infraestrutura escolar inadequada', 'Falta de participação da comunidade nas decisões',
                 'Currículo pouco relacionado à realidade quilombola',
                 'Alimentação escolar que não valoriza a produção local quilombola',
                 'Falta ou precariedade de internet/conectividade',
                 'Falta de professores/as e outros profissionais',
                 'Desigualdade no acesso ao esporte, especialmente para meninas',
                 'Dificuldade de acesso e permanência dos estudantes',
                 'Fechamento de salas/turmas', 'Fechamento de escolas']),
]

# Colunas usadas só em agregados, ou que nunca saem (ver o topo do arquivo).
# 'acha' segue a mesma regra das perguntas.
COLUNAS_APOIO = {
    'carimbo': 'carimbo de data/hora',
    'nascimento': 'data de nascimento',
    'ufComunidade': 'estado do pais sua comunidade',
    'municipioComunidade': 'nome do municipio da sua comunidade',
    # "3- Município" e "4 - Estado:" (as da escola). Expressão regular sobre o
    # cabeçalho já normalizado ("4 estado"), para não confundir com as da comunidade.
    'ufEscola': r'^\d+ estado$',
    'municipioEscola': r'^\d+ municipio$',
    'deficiencia': 'possui algum tipo de deficiencia',
    'abandono': 'precisou abandonar a escola',
}
# Colunas que o script reconhece e descarta de propósito. Estão listadas só para
# o log não avisar "coluna nova" toda vez. Nenhuma delas é lida.
COLUNAS_DESCARTADAS = ['endereco de e-mail', 'nome completo', 'se respondeu sim, qual', 'em qual ano precisou',
                       'por qual motivou', 'nome da escola', 'descreva qual o tipo de dificuldade',
                       'violacao de direitos', 'monitora pedagogica']

BLOCOS = OrderedDict([
    ('perfil', 'Quem respondeu'),
    ('territorio', 'Território e participação'),
    ('acesso', 'Escola, matrícula e transporte'),
    ('estrutura', 'Estrutura da escola'),
    ('identidade', 'Identidade, currículo e formação'),
    ('racismo', 'Racismo, gênero e participação'),
    ('obstaculos', 'Obstáculos ao direito'),
])


# ----------------------------------------------------------------------
# TEXTO
# ----------------------------------------------------------------------
def sem_acento(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c))


def normaliza(s):
    """'Município de Regeneração.' -> 'municipio de regeneracao'"""
    s = sem_acento(s).lower()
    s = re.sub(r'[^a-z0-9/ ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def decodifica(b):
    for enc in ('utf-8-sig', 'latin-1'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode('latin-1', errors='replace')


# ----------------------------------------------------------------------
# LEITURA DA PLANILHA
# ----------------------------------------------------------------------
def baixa(url, rotulo):
    print(f"Baixando {rotulo}…")
    req = urllib.request.Request(url, headers={"User-Agent": "painel-enfmq/1.0"})
    for tentativa in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return decodifica(resp.read())
        except Exception as e:
            if tentativa == 3:
                raise RuntimeError(f"não foi possível baixar {rotulo} ({e}).") from e
            print(f"  falha ({e}); nova tentativa {tentativa + 1}/3…")
            time.sleep(5 * tentativa)


def le_planilha(url=None, arquivo=None):
    if arquivo:
        print(f"Lendo o arquivo {arquivo}")
        with open(arquivo, 'rb') as f:
            texto = decodifica(f.read())
    else:
        texto = baixa(url, "a planilha de respostas")
    # Se a planilha deixar de estar publicada, o Google devolve uma página de
    # login em HTML, e não um erro. Sem esta checagem, o script leria o HTML como
    # se fosse CSV e publicaria um painel vazio.
    if texto.lstrip()[:15].lower().startswith(('<!doctype', '<html')):
        raise RuntimeError("o link devolveu uma página da web, não um CSV. Confira se a planilha continua "
                           "publicada (Arquivo → Compartilhar → Publicar na web) e se o link termina em "
                           "output=csv.")
    linhas = list(csv.reader(io.StringIO(texto)))
    if not linhas:
        raise RuntimeError("a planilha veio vazia.")
    cabecalho = [h.replace('\xa0', ' ').strip() for h in linhas[0]]
    dados = [l for l in linhas[1:] if any(c.strip() for c in l)]
    print(f"{len(dados)} respostas, {len(cabecalho)} colunas.")
    return cabecalho, dados


def acha_coluna(cabecalho, padrao):
    """Índice da coluna cujo cabeçalho contém o trecho (ou casa a expressão)."""
    if padrao is None:
        return None
    normais = [normaliza(h) for h in cabecalho]
    if padrao.startswith('^'):
        rx = re.compile(padrao)
        for i, h in enumerate(normais):
            if rx.search(h):
                return i
        return None
    alvo = normaliza(padrao)
    for i, h in enumerate(normais):
        if alvo in h:
            return i
    return None


def mapeia_colunas(cabecalho):
    usadas, indice = set(), {}
    for p in PERGUNTAS:
        if p['acha'] is None:
            continue
        i = acha_coluna(cabecalho, p['acha'])
        if i is None:
            print(f"AVISO: não achei a pergunta '{p['rot']}' (procurei por '{p['acha']}'). "
                  "Ela vai aparecer sem dados. Se o texto da pergunta mudou no formulário, ajuste 'acha'.")
        else:
            indice[p['k']] = i
            usadas.add(i)
    for k, padrao in COLUNAS_APOIO.items():
        i = acha_coluna(cabecalho, padrao)
        if i is None:
            print(f"AVISO: não achei a coluna de apoio '{k}' (procurei por '{padrao}').")
        else:
            indice[k] = i
            usadas.add(i)
    for padrao in COLUNAS_DESCARTADAS:
        i = acha_coluna(cabecalho, padrao)
        if i is not None:
            usadas.add(i)
    novas = [cabecalho[i] for i in range(len(cabecalho)) if i not in usadas]
    if novas:
        print("AVISO: colunas que o painel não usa (pergunta nova no formulário?). "
              "Para incluí-las, descreva-as em PERGUNTAS:")
        for n in novas:
            print(f"  - {n[:120]!r}")
    return indice


# ----------------------------------------------------------------------
# LIMPEZA DAS RESPOSTAS
# ----------------------------------------------------------------------
def resposta_unica(p, bruto):
    """Devolve a categoria, ou None se a pessoa não respondeu."""
    v = (bruto or '').strip()
    if not v or v in ('.', '-'):
        return None
    if p['k'] == 'meioTransporte':
        return meio_transporte(v)
    if p['k'] == 'tempoTransporte':
        return tempo_transporte(v)
    v = p.get('sinonimos', {}).get(v, v)
    # a comparação ignora maiúsculas e acento: "Não Participo" == "Não participo"
    por_normal = {normaliza(o): o for o in p['ordem']}
    achou = por_normal.get(normaliza(v))
    if achou:
        return achou
    # fora da lista: é o "Outro: ___" que a pessoa escreveu
    return 'Outro' if 'Outro' in p['ordem'] else OUTRA


def resposta_escala(p, bruto):
    v = (bruto or '').strip()
    try:
        n = int(float(v.replace(',', '.')))
    except ValueError:
        return None
    return str(n) if p['min'] <= n <= p['max'] else None


def resposta_multipla(p, bruto, desconhecidas):
    """
    Lista das opções marcadas.

    O Google junta as opções marcadas com ", ". Separar pela vírgula quebraria a
    opção "Desigualdade no acesso ao esporte, especialmente para meninas", que tem
    vírgula no meio. Então procuramos cada opção conhecida dentro do texto inteiro,
    e o que sobrar é o "Outro: ___" que a pessoa escreveu.
    """
    texto = (bruto or '').strip()
    if not texto or texto in ('.', '-'):
        return None
    marcadas, resto = [], texto
    for o in p['opcoes']:
        if o in resto:
            marcadas.append(o)
            resto = resto.replace(o, ' ')
    resto_limpo = re.sub(r'[\s,.;]+', ' ', resto).strip()
    if resto_limpo:
        rotulo = None
        reconhecida = False
        for padrao, nome in p.get('livres', []):
            if re.search(padrao, normaliza(resto_limpo)):
                rotulo, reconhecida = nome, True
                break
        if not reconhecida:
            rotulo = OUTRA
            desconhecidas[p['k']][resto_limpo[:80]] += 1
        if rotulo is not None and rotulo not in marcadas:
            marcadas.append(rotulo)
    return marcadas or None


def meio_transporte(v):
    t = normaliza(v)
    achados = []
    for padrao, nome in [(r'onibus', 'Ônibus escolar'), (r'\bvan\b|kombi|kombe', 'Van ou kombi escolar'),
                         (r'barco|canoa|rabeta|lancha', 'Barco escolar'), (r'coletivo', 'Transporte coletivo'),
                         (r'particular|familia|moto|carro', 'Transporte da família'),
                         (r'\ba pe\b|bicicleta|caminhando', 'A pé ou de bicicleta')]:
        if re.search(padrao, t):
            achados.append(nome)
    if len(achados) > 1:
        return 'Mais de um meio'
    if achados:
        return achados[0]
    if 'prefeitura' in t:
        return 'Van ou kombi escolar' if 'kombi' in t else 'Ônibus escolar'
    return OUTRA


def tempo_transporte(v):
    """
    As opções do formulário são faixas, mas há "Outro: ___" com texto livre
    ("38 minutos", "1:30", "Saio 6:10, chego 7:15"). Convertemos em minutos para
    pôr cada resposta na faixa certa, em vez de perdê-la como "outra".
    """
    t = normaliza(v)
    if 'nao se aplica' in t:
        return NA
    if 'menos de 1' in t or 'perto' in t:
        return 'Menos de 1 hora'
    if re.search(r'entre 1 e 2|1 a 2', t):
        return 'Entre 1 e 2 horas'
    if re.search(r'entre 2 e 3|2 a 3', t):
        return 'Entre 2 e 3 horas'
    if 'mais de 3' in t:
        return 'Mais de 3 horas'
    minutos = None
    horarios = re.findall(r'(\d{1,2})[:h](\d{2})', sem_acento(v).lower())
    if len(horarios) >= 2:          # "saio 6:10, chego 7:15"
        (h1, m1), (h2, m2) = horarios[0], horarios[1]
        minutos = (int(h2) * 60 + int(m2)) - (int(h1) * 60 + int(m1))
    elif len(horarios) == 1:        # "1:30"
        minutos = int(horarios[0][0]) * 60 + int(horarios[0][1])
    else:
        mins = re.findall(r'(\d+)\s*min', t)
        horas = re.findall(r'(\d+)\s*(?:h\b|hora)', t)
        if mins or horas:
            minutos = sum(int(m) for m in mins) + 60 * sum(int(h) for h in horas)
    if minutos is None or minutos < 0:
        return OUTRA
    if minutos < 60:
        return 'Menos de 1 hora'
    if minutos <= 120:
        return 'Entre 1 e 2 horas'
    if minutos <= 180:
        return 'Entre 2 e 3 horas'
    return 'Mais de 3 horas'


def le_data(txt):
    txt = (txt or '').strip()
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def faixa_etaria(nascimento, resposta):
    """Idade na data da resposta, em faixa. A data de nascimento em si nunca sai."""
    n = le_data(nascimento)
    if n is None:
        return None
    ref = resposta or datetime.now()
    idade = ref.year - n.year - ((ref.month, ref.day) < (n.month, n.day))
    if idade < 10 or idade > 70:      # data digitada errada (ex.: o ano de hoje)
        return None
    if idade <= 14:
        return 'Até 14 anos'
    if idade <= 17:
        return '15 a 17 anos'
    if idade <= 20:
        return '18 a 20 anos'
    return '21 anos ou mais'


def uf_de(texto):
    """'BA, Bahia' -> 'BA'. Aceita também só o nome do estado."""
    t = (texto or '').strip()
    m = re.match(r'^([A-Za-z]{2})\b', t)
    if m and m.group(1).upper() in UF_NOMES:
        return m.group(1).upper()
    por_nome = {normaliza(v): k for k, v in UF_NOMES.items()}
    return por_nome.get(normaliza(t))


# ----------------------------------------------------------------------
# MUNICÍPIOS (só para o mapa de contagens)
# ----------------------------------------------------------------------
def carrega_municipios():
    if os.path.exists(MUNICIPIOS_CACHE):
        with open(MUNICIPIOS_CACHE, 'rb') as f:
            texto = decodifica(f.read())
    else:
        texto = baixa(MUNICIPIOS_URL, "os centróides municipais do IBGE (uma vez só)")
        with open(MUNICIPIOS_CACHE, 'w', encoding='utf-8') as f:
            f.write(texto)
    por_uf = {}
    for l in csv.DictReader(io.StringIO(texto)):
        try:
            uf = UF_CODIGO[l['codigo_ibge'][:2]]
            por_uf.setdefault(uf, []).append(
                {'ibge': l['codigo_ibge'], 'nome': l['nome'], 'norm': normaliza(l['nome']),
                 'lat': round(float(l['latitude']), 4), 'lon': round(float(l['longitude']), 4)})
        except (KeyError, ValueError):
            continue
    return por_uf


def acha_municipio(texto, uf, por_uf):
    """
    A pergunta de município é aberta, então chega de tudo: "Cachoeira-Ba",
    "Comunidade Quilombola de Picadas, município de Ipanguaçu-RN", "MORRO DO CHAPÉU".
    Tentamos, nesta ordem, dentro da UF informada:
      1. apelidos conhecidos (MUNICIPIO_APELIDOS), para quem escreveu só a comunidade;
      2. o nome de um município aparecendo inteiro no texto (vence o mais longo,
         para "São Francisco do Conde" não virar "Conde");
      3. um nome muito parecido (erro de digitação: "Moraujo" -> "Moraújo").
    """
    lista = por_uf.get(uf) or []
    t = normaliza(texto)
    if not t or not lista:
        return None
    por_nome = {m['norm']: m for m in lista}
    for (u, trecho), nome in MUNICIPIO_APELIDOS.items():
        if u == uf and trecho in t:
            return por_nome.get(normaliza(nome))
    candidatos = [m for m in lista if re.search(r'\b' + re.escape(m['norm']) + r'\b', t)]
    if candidatos:
        return max(candidatos, key=lambda m: len(m['norm']))
    pedacos = [t] + [normaliza(p) for p in re.split(r'[,/()\-]| em | de ', sem_acento(texto).lower()) if p.strip()]
    for p in pedacos:
        perto = difflib.get_close_matches(p, list(por_nome), n=1, cutoff=0.86)
        if perto:
            return por_nome[perto[0]]
    return None


def conta_municipios(linhas, iuf, imun, por_uf, rotulo):
    cont, sem = {}, Counter()
    for l in linhas:
        uf = uf_de(l[iuf]) if iuf is not None and iuf < len(l) else None
        txt = l[imun] if imun is not None and imun < len(l) else ''
        m = acha_municipio(txt, uf, por_uf) if uf else None
        if m is None:
            sem[f"{txt.strip()[:60]} ({uf or '?'})"] += 1
            continue
        c = cont.setdefault(m['ibge'], {'nome': m['nome'], 'uf': uf, 'lat': m['lat'], 'lon': m['lon'], 'n': 0})
        c['n'] += 1
    if sem:
        print(f"AVISO: {sum(sem.values())} resposta(s) com {rotulo} não identificado (ficam fora do mapa). "
              "Para corrigir, acrescente em MUNICIPIO_APELIDOS:")
        for k, v in sem.most_common():
            print(f"  - {k} ×{v}")
    return sorted(cont.values(), key=lambda c: -c['n']), sum(sem.values())


# ----------------------------------------------------------------------
# ANONIMATO
# ----------------------------------------------------------------------
NAO_DIVULGADO = 'Grupo pequeno (não divulgado)'
REGIAO_NAO_DIVULGADA = 'Não divulgada (grupo pequeno)'
UF_NAO_DIVULGADA = 'UF com menos de {k} respostas'


def agrupa_grupos_pequenos(registros, vars_meta):
    """
    Nas variáveis marcadas qi=True, uma categoria com menos de MINIMO_GRUPO
    pessoas vira 'Grupo pequeno (não divulgado)'.

    Por quê: nenhuma resposta isolada identifica alguém, mas a combinação pode.
    Se só uma pessoa do Amapá respondeu, quem sabe que ela respondeu descobre, pelo
    painel, tudo o que ela disse sobre racismo na escola dela. Agrupar as
    categorias raras quebra essa combinação. Conforme chegam respostas, as
    categorias passam do limite e voltam a aparecer sozinhas.

    A UF tem um cuidado a mais. Se o Amapá é a única UF pequena do Norte,
    "UF não divulgada + região Norte" aponta o Amapá do mesmo jeito. Então a região
    também é escondida, mas só quando as UFs pequenas daquela região, somadas, não
    chegam a MINIMO_GRUPO. No Nordeste, Ceará + Paraíba + Sergipe + Piauí juntos
    já formam um grupo grande o bastante, e a região fica.
    """
    for p in vars_meta:
        if not p.get('qi') or p.get('agregado'):
            continue
        k = p['k']
        cont = Counter(r[k] for r in registros if r.get(k) is not None)
        pequenas = {c for c, n in cont.items() if n < MINIMO_GRUPO}
        if not pequenas:
            continue
        rotulo = UF_NAO_DIVULGADA.format(k=MINIMO_GRUPO) if k == 'uf' else NAO_DIVULGADO
        if k == 'uf':
            por_regiao = Counter()
            for uf in pequenas:
                por_regiao[UF_REGIAO.get(uf)] += cont[uf]
            regioes_escondidas = {g for g, n in por_regiao.items() if n < MINIMO_GRUPO}
        for r in registros:
            if r.get(k) in pequenas:
                if k == 'uf' and UF_REGIAO.get(r[k]) in regioes_escondidas:
                    r['regiao'] = REGIAO_NAO_DIVULGADA
                r[k] = rotulo
        # a categoria agrupada sai da lista, e junto saem a cor e o rótulo curto
        # dela; o grupo novo entra no fim, com o tom '?' (cinza, fora da escala)
        manter = [i for i, c in enumerate(p['ordem']) if c not in pequenas]
        if p.get('tons'):
            p['tons'] = ''.join(p['tons'][i] for i in manter if i < len(p['tons'])) + '?'
        if p.get('curtos'):
            p['curtos'] = [p['curtos'][i] for i in manter] + [rotulo]
        p['ordem'] = [p['ordem'][i] for i in manter] + [rotulo]
        p['agrupadas'] = len(pequenas)
        print(f"Anonimato: em '{p['rot']}', {len(pequenas)} categoria(s) com menos de {MINIMO_GRUPO} "
              f"pessoas foram agrupadas ({sum(cont[c] for c in pequenas)} resposta(s)).")


# ----------------------------------------------------------------------
# MONTAGEM
# ----------------------------------------------------------------------
def monta_registros(cabecalho, dados, indice):
    desconhecidas = {p['k']: Counter() for p in PERGUNTAS if p['tipo'] == 'multipla'}
    registros = []
    for l in dados:
        def col(k):
            i = indice.get(k)
            return l[i] if i is not None and i < len(l) else ''
        r = {}
        quando = le_data(col('carimbo'))
        r['_data'] = quando.strftime('%Y-%m-%d') if quando else None   # só para o agregado diário
        uf = uf_de(col('ufComunidade'))
        r['uf'] = uf
        r['regiao'] = UF_REGIAO.get(uf)
        r['faixaEtaria'] = faixa_etaria(col('nascimento'), quando)
        for p in PERGUNTAS:
            if p['k'] == 'faixaEtaria':
                continue
            bruto = col(p['k'])
            if p['tipo'] == 'unica':
                r[p['k']] = resposta_unica(p, bruto)
            elif p['tipo'] == 'escala':
                r[p['k']] = resposta_escala(p, bruto)
            else:
                r[p['k']] = resposta_multipla(p, bruto, desconhecidas)
        r['_deficiencia'] = normaliza(col('deficiencia'))
        r['_abandono'] = normaliza(col('abandono'))
        registros.append(r)
    for k, c in desconhecidas.items():
        if c:
            print(f"Respostas livres em '{k}' sem categoria (contam como '{OUTRA}'): "
                  + '; '.join(f'{t!r}×{n}' for t, n in c.most_common(8)))
    return registros


def vars_do_painel():
    """Metadados das variáveis, na ordem em que aparecem. UF e região entram primeiro."""
    ufs_ordem = sorted(UF_NOMES)
    meta = [
        dict(k='regiao', rot='Região (da comunidade)', tipo='unica', bloco='local', qi=False,
             ordem=['Norte', 'Nordeste', 'Centro-Oeste', 'Sudeste', 'Sul'], tons='ccccc'),
        # (a região escondida por agrupamento entra no fim da ordem, sem cor própria)
        dict(k='uf', rot='UF (da comunidade)', tipo='unica', bloco='local', qi=True,
             ordem=ufs_ordem, tons='c' * len(ufs_ordem)),
    ]
    for p in PERGUNTAS:
        m = {x: p[x] for x in ('k', 'rot', 'tipo', 'bloco', 'qi', 'agregado', 'ordem', 'tons', 'curtos',
                               'opcoes', 'min', 'max', 'polaridade', 'extremos') if x in p}
        if p['tipo'] == 'escala':
            m['ordem'] = [str(i) for i in range(p['min'], p['max'] + 1)]
        if p['tipo'] == 'multipla':
            extras = [nome for _, nome in p.get('livres', []) if nome] + [OUTRA]
            m['ordem'] = p['opcoes'] + [e for e in extras if e not in p['opcoes']]
        meta.append(m)
    return meta


def textos_das_perguntas(cabecalho, indice):
    """Texto integral de cada pergunta, para o painel citar a pergunta como foi feita."""
    out = {}
    for p in PERGUNTAS:
        i = indice.get(p['k'])
        if i is not None:
            t = re.sub(r'\s+', ' ', cabecalho[i]).strip()
            out[p['k']] = re.sub(r'^\s*\d+\s*[-–.]\s*', '', t)
    out['faixaEtaria'] = 'Calculada a partir da data de nascimento, na data da resposta.'
    out['uf'] = 'A qual estado do país sua comunidade pertence?'
    out['regiao'] = 'Derivada do estado da comunidade.'
    return out


def monta_pacote(registros, meta):
    """
    Formato colunar, como no painel de escolas: um array por variável, em vez de um
    objeto por pessoa. Cada posição guarda o ÍNDICE da categoria em meta.ordem
    (-1 = não respondeu). Nas de múltipla escolha guarda uma máscara de bits: o bit
    i ligado quer dizer que a pessoa marcou a opção i.
    """
    colunas = {}
    for m in meta:
        if m.get('agregado'):
            continue
        k, ordem = m['k'], m['ordem']
        pos = {c: i for i, c in enumerate(ordem)}
        col = []
        for r in registros:
            v = r.get(k)
            if v is None:
                col.append(-1)
            elif m['tipo'] == 'multipla':
                mask = 0
                for o in v:
                    mask |= 1 << pos[o]
                col.append(mask)
            else:
                if v not in pos:              # categoria nova que não estava na ordem
                    ordem.append(v)
                    pos[v] = len(ordem) - 1
                col.append(pos[v])
        colunas[k] = col
    return colunas


def conta_agregados(registros, meta):
    """Totais nacionais das variáveis marcadas agregado=True (não vão pessoa a pessoa)."""
    out = {}
    for m in meta:
        if not m.get('agregado'):
            continue
        cont = Counter(r.get(m['k']) for r in registros if r.get(m['k']) is not None)
        for c in cont:
            if c not in m['ordem']:
                m['ordem'].append(c)
        out[m['k']] = [cont.get(c, 0) for c in m['ordem']]
    return out


def resumo(registros, dados_brutos, ufs_reais):
    def conta(campo, valor='sim'):
        com = [r[campo] for r in registros if r[campo]]
        return {'sim': sum(1 for v in com if v == valor), 'n': len(com)}
    datas = sorted(r['_data'] for r in registros if r['_data'])
    por_dia = Counter(datas)
    return {
        'deficiencia': conta('_deficiencia'),
        'abandono': conta('_abandono'),
        'primeira': datas[0] if datas else None,
        'ultima': datas[-1] if datas else None,
        'porDia': sorted(por_dia.items()),
        'ufs': len(ufs_reais),
    }


def hoje_br():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        return datetime.now()


def gera_pagina(pacote, saida):
    with open(TEMPLATE_PATH, encoding='utf-8') as f:
        tpl = f.read()
    dados = json.dumps(pacote, ensure_ascii=False, separators=(',', ':'))
    # impede que um texto com "</script>" feche o bloco de script antes da hora
    dados = dados.replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    r = pacote['resumo']
    fmt_data = lambda iso: datetime.strptime(iso, '%Y-%m-%d').strftime('%d/%m/%Y') if iso else '—'
    subs = {
        '__DATA_GERACAO__': pacote['gerado'],
        '__TOTAL_RESPOSTAS__': f"{pacote['n']:,}".replace(',', '.'),
        '__TOTAL_UFS__': str(r['ufs']),
        '__TOTAL_MUNICIPIOS__': str(len(pacote['mapa']['comunidade'])),
        '__PERIODO__': f"{fmt_data(r['primeira'])} a {fmt_data(r['ultima'])}",
        '__MINIMO_GRUPO__': str(MINIMO_GRUPO),
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)
    restantes = re.findall(r'__[A-Z_]+__', tpl.replace('__DATA_JSON__', ''))
    if restantes:
        raise RuntimeError(f"placeholders não substituídos no template: {sorted(set(restantes))}")
    tpl = tpl.replace('__DATA_JSON__', dados)
    # grava num arquivo temporário e só depois troca: se algo falhar no meio, o
    # index.html publicado continua sendo o de ontem, inteiro
    tmp = saida + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(tpl)
    os.replace(tmp, saida)
    print(f"\n{saida} gerado: {pacote['n']} respostas, {len(tpl.encode('utf-8')) / 1e3:.0f} KB.")


def confere_vazamento(saida, cabecalho, dados):
    """
    Última trava antes de publicar: procura no HTML gerado qualquer nome, e-mail ou
    data de nascimento da planilha. Se achar, apaga o arquivo e para com erro.
    Não deveria acontecer nunca. Existe para o dia em que alguém mexer no script
    e, sem querer, deixar passar uma coluna pessoal.
    """
    with open(saida, encoding='utf-8') as f:
        html = f.read().lower()
    suspeitos = []
    for padrao in ('nome completo', 'endereco de e-mail', 'data de nascimento'):
        i = acha_coluna(cabecalho, padrao)
        if i is None:
            continue
        for l in dados:
            v = (l[i] if i < len(l) else '').strip().lower()
            # nomes curtos ("ana") podem aparecer por acaso no texto; só testamos
            # valores longos o bastante para serem únicos
            if len(v) >= 8 and v in html:
                suspeitos.append(padrao)
                break
    if suspeitos:
        os.remove(saida)
        raise RuntimeError(f"o HTML gerado continha dados pessoais ({', '.join(suspeitos)}). "
                           f"Arquivo apagado, nada foi publicado. Revise o script.")
    print("Conferência de privacidade: nenhum nome, e-mail ou data de nascimento no HTML.")



def main():
    ap = argparse.ArgumentParser(description="Gera o painel do Diagnóstico da EEQ (ENFMQ) a partir das respostas.")
    ap.add_argument("--url", help="link do CSV publicado (ou use a variável de ambiente PLANILHA_CSV_URL)")
    ap.add_argument("--arquivo", help="CSV baixado à mão, em vez do link")
    ap.add_argument("--saida", default=SAIDA_PADRAO, help=f"arquivo a gerar (padrão: {SAIDA_PADRAO})")
    args = ap.parse_args()
    url = args.url or os.environ.get('PLANILHA_CSV_URL', '').strip()

    try:
        if not args.arquivo and not url:
            raise RuntimeError("informe a planilha: --arquivo respostas.csv, --url LINK, ou a variável "
                               "PLANILHA_CSV_URL (no GitHub, ela vem do segredo de mesmo nome).")
        if not os.path.exists(TEMPLATE_PATH):
            raise RuntimeError(f"o arquivo {TEMPLATE_PATH} precisa estar na mesma pasta que o script.")

        cabecalho, dados = le_planilha(url=url, arquivo=args.arquivo)
        if len(dados) < MINIMO_RESPOSTAS:
            raise RuntimeError(f"só vieram {len(dados)} respostas (mínimo esperado: {MINIMO_RESPOSTAS}). "
                               f"{args.saida} não foi alterado.")
        indice = mapeia_colunas(cabecalho)
        registros = monta_registros(cabecalho, dados, indice)

        por_uf = carrega_municipios()
        mapa_com, sem_com = conta_municipios(dados, indice.get('ufComunidade'), indice.get('municipioComunidade'),
                                             por_uf, "município da comunidade")
        mapa_esc, sem_esc = conta_municipios(dados, indice.get('ufEscola'), indice.get('municipioEscola'),
                                             por_uf, "município da escola")
        ufs_reais = {r['uf'] for r in registros if r['uf']}
        res = resumo(registros, dados, ufs_reais)

        meta = vars_do_painel()
        agregados = conta_agregados(registros, meta)
        agrupa_grupos_pequenos(registros, meta)
        colunas = monta_pacote(registros, meta)

        pacote = {
            'n': len(registros),
            'gerado': hoje_br().strftime('%d/%m/%Y às %H:%M'),
            'minimoGrupo': MINIMO_GRUPO,
            'blocos': list(BLOCOS.items()),
            'vars': meta,
            'perguntas': textos_das_perguntas(cabecalho, indice),
            'colunas': colunas,
            'agregados': agregados,
            'resumo': res,
            'mapa': {'comunidade': mapa_com, 'escola': mapa_esc,
                     'semLocalComunidade': sem_com, 'semLocalEscola': sem_esc},
        }
        gera_pagina(pacote, args.saida)
        confere_vazamento(args.saida, cabecalho, dados)
    except (RuntimeError, OSError) as e:
        print(f"\nERRO: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
