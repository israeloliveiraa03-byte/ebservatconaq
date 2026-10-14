# Diagnóstico da Educação Escolar Quilombola · ENFMQ

Painel público com as respostas do formulário *Diagnóstico da Educação Escolar
Quilombola – ENFMQ* (CONAQ). A página se atualiza sozinha todo dia: o GitHub lê a
planilha do Google, tira os dados pessoais e gera um `index.html` novo, que a
Vercel publica.

```
planilha do Google  ──(todo dia, 6h)──►  GitHub Actions roda atualizar_dados.py
 (respostas do form)                       │  lê a planilha
                                           │  tira nome, e-mail, nascimento, escola…
                                           │  agrupa categorias pequenas
                                           ▼
                                      index.html  ──►  Vercel publica
```

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `atualizar_dados.py` | Lê a planilha e gera o `index.html`. Todas as regras (que pergunta vai para qual eixo, o que é dado pessoal, cores) estão descritas no topo dele. |
| `template.html` | O desenho da página. Tem marcadores como `__DATA_JSON__`, que o script troca pelos dados. |
| `index.html` | A página pronta. **Não edite à mão**: ela é refeita todo dia a partir do template. |
| `municipios-ibge.csv` | Centro de cada município brasileiro (IBGE), usado no mapa. |
| `.github/workflows/atualizar.yml` | A rotina diária do GitHub. |
| `.gitignore` | Impede que um CSV de respostas vá para o GitHub por engano. |

## Como colocar no ar (uma vez só)

**1. Criar o repositório.** No GitHub, crie um repositório novo (ex.:
`diagnostico-eeq`) e suba todos os arquivos desta pasta, **inclusive a pasta
`.github`**. Ela começa com ponto e pode ficar escondida no seu computador. No
macOS, aperte `Cmd + Shift + .` no Finder para vê-la.

**2. Guardar o link da planilha como segredo.** No repositório:
*Settings → Secrets and variables → Actions → New repository secret*.

- Name: `PLANILHA_CSV_URL`
- Secret: o link do CSV publicado (o que termina em `output=csv`)

> **Por que segredo?** Um link "publicado na web" do Google abre para qualquer
> pessoa que o tenha, sem login. A planilha tem nome, e-mail e data de nascimento
> das estudantes. Escrito no código, o link ficaria visível para todo mundo que
> abrisse o repositório. Como segredo, só o GitHub o lê, na hora de rodar.

**3. Liberar a rotina para salvar arquivos.** *Settings → Actions → General →
Workflow permissions* → marque **Read and write permissions** → Save.

**4. Rodar a primeira vez.** Aba *Actions* → *Atualizar painel* → *Run workflow*.
Em um ou dois minutos aparece um ✓ verde. Clique na execução para ler o log, que
explica o que o script fez (quantas respostas, o que foi agrupado, quais
municípios não foram reconhecidos).

**5. Ligar na Vercel.** Em vercel.com, *Add New → Project*, escolha o repositório
e clique em *Deploy*. Não é preciso configurar nada: é uma página HTML. Daqui
para frente, cada atualização diária vira uma publicação nova, sozinha.

## O dia a dia

- **Não há nada a fazer.** Todo dia às 6h o painel se atualiza. Quer ver uma
  resposta nova antes disso? *Actions → Atualizar painel → Run workflow*.
- **Se der erro**, o GitHub manda um e-mail e o painel publicado **continua o de
  ontem**. O script nunca publica uma página pela metade. Os erros mais comuns:
  - *"o link devolveu uma página da web, não um CSV"*: a planilha deixou de estar
    publicada. No Google Planilhas: *Arquivo → Compartilhar → Publicar na web*.
  - *"só vieram N respostas"*: a planilha veio quase vazia (troca de aba, por
    exemplo). Confira se o link ainda aponta para a aba de respostas.
- **Município não reconhecido.** O município é escrito à mão no formulário
  ("Santiago do Iguape", "Cachoeira-Ba"). O log lista os que o script não
  reconheceu. Para ensinar, acrescente uma linha em `MUNICIPIO_APELIDOS`, no topo
  do `atualizar_dados.py`. Hoje ficam de fora do mapa: *Passagem do Meio* (BA),
  *Pau D'arco* (AL) e *Sítio Vassourinha* (CE).

## Se o formulário mudar

O script acha cada pergunta por um **trecho do texto**, e não pelo número dela.
Por isso, renumerar ou reordenar o formulário não quebra nada.

- **Pergunta nova:** o log avisa *"colunas que o painel não usa"*. Para ela entrar
  no painel, copie um bloco `dict(...)` parecido em `PERGUNTAS` e ajuste o trecho
  (`acha`), o título (`rot`), o eixo (`bloco`) e as opções (`ordem`).
- **Texto de pergunta alterado:** se o trecho em `acha` deixar de existir, o log
  avisa *"não achei a pergunta…"*. Basta atualizar o trecho.
- **Opção nova numa pergunta existente:** ela aparece como "Outra resposta" até
  ser acrescentada em `ordem` (ou em `opcoes`, nas de múltipla escolha).

## Privacidade: o que o painel publica

| O quê | Como sai |
|---|---|
| Nome, e-mail, nome da escola, monitora, respostas escritas | **Nunca** |
| Data de nascimento | Só como faixa etária, e só no total da base |
| Horário de envio | Só como nº de respostas por dia |
| Município (da comunidade e da escola) | Só como contagem no mapa, sem ligação com as respostas |
| Deficiência e abandono escolar | Só o total da base, sem o tipo nem o motivo |
| Faixa etária, turno, trabalho | Só o total da base (não filtram nem cruzam) |
| UF, gênero, raça/cor, série | Por resposta, com categorias de menos de 5 pessoas agrupadas |
| Demais perguntas de escolha | Por resposta, sem nada que identifique quem respondeu |

Além disso, a página se recusa a mostrar recortes ou linhas de cruzamento com
menos de 5 respostas. Antes de salvar, o script confere se algum nome, e-mail ou
data de nascimento da planilha foi parar no HTML. Se tiver ido, ele apaga o
arquivo e para com erro.

**Um limite honesto.** A página guarda as respostas de escolha pessoa a pessoa
(sem identificação), porque é isso que permite filtrar e cruzar. Uma pessoa com
conhecimento técnico, que soubesse a UF, o gênero e a série de uma estudante
específica, poderia tentar achá-la nesses dados. Foi por isso que idade, turno e
trabalho saíram dos dados por pessoa. Para apertar mais, mude o limite
`MINIMO_GRUPO` (ex.: de 5 para 10) ou acrescente `agregado=True` a outras
perguntas em `PERGUNTAS`.

**Recomendação para a planilha.** Hoje o link publicado entrega a planilha
inteira, com nomes e e-mails, a quem o tiver. Uma alternativa mais segura é criar
outra aba que puxe só as colunas sem dado pessoal (por exemplo, com
`=QUERY('Respostas ao formulário 1'!A:BB; "select A, D, F, …")`) e publicar
**apenas essa aba**. O script funciona do mesmo jeito. Só a faixa etária some se
a data de nascimento ficar de fora.

## Rodar no seu computador (opcional)

Precisa só de Python 3.9 ou mais novo. Baixe as respostas em CSV (*Arquivo →
Fazer download → .csv*) para esta pasta e rode:

```
python3 atualizar_dados.py --arquivo respostas.csv
```

Depois abra o `index.html` no navegador. O `.gitignore` impede que o CSV de
respostas suba para o GitHub.
