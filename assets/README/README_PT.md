<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor Logo" width="150" style="border-radius: 15px;">

# DeepTutor: Seu Assistente Pessoal de Aprendizado

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](LICENSE)
[![Feishu](https://img.shields.io/badge/Feishu-Group-blue?style=flat)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-green?style=flat&logo=wechat)](./Communication.md)



[**Início Rápido**](#início-rápido) · [**Módulos Principais**](#módulos-principais) · [**Perguntas Frequentes**](#perguntas-frequentes)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

<div align="center">

| ⚡ **Q&A de Conhecimento de Documentos Massivos**  |  📈 **Visualização de Aprendizado Interativo**  | <br>
| 🧠 **Reforço de Conhecimento**  |  🔬 **Pesquisa Profunda e Geração de Ideias** |

</div>

---
> **[2026.1.1]** Feliz Ano Novo! Junte-se às nossas [GitHub Discussions](https://github.com/HKUDS/DeepTutor/discussions) — molde o futuro do DeepTutor! 💬

> **[2025.12.30]** Visite nosso [Site Oficial](https://hkuds.github.io/DeepTutor/) para mais detalhes!

> **[2025.12.29]** DeepTutor v0.1 já está disponível! ✨
---

## Características Principais do DeepTutor

### 📚 Q&A de Conhecimento de Documentos Massivos
• **Base de Conhecimento Inteligente**: Faça upload de livros didáticos, artigos de pesquisa, manuais técnicos e documentos específicos do domínio. Construa um repositório de conhecimento abrangente alimentado por IA para acesso instantâneo.<br>
• **Resolução de Problemas Multi-Agente**: Arquitetura de raciocínio de duplo loop com RAG, busca na web, busca de artigos e execução de código—fornecendo soluções passo a passo com citações precisas.

### 🎨 Visualização de Aprendizado Interativo
• **Simplificação e Explicações do Conhecimento**: Transforme conceitos complexos, conhecimento e algoritmos em auxílios visuais fáceis de entender, decomposições detalhadas passo a passo e demonstrações interativas envolventes.<br>
• **Q&A Personalizado**: Conversas conscientes do contexto que se adaptam ao seu progresso de aprendizado, com páginas interativas e rastreamento de conhecimento baseado em sessões.

### 🎯 Reforço de Conhecimento com Gerador de Problemas de Prática
• **Criação de Exercícios Inteligentes**: Gere questionários direcionados, problemas de prática e avaliações personalizadas adaptadas ao seu nível atual de conhecimento e objetivos de aprendizado específicos.<br>
• **Simulação de Exame Autêntica**: Faça upload de exames de referência para gerar questões de prática que correspondem perfeitamente ao estilo, formato e dificuldade originais—fornecendo preparação realista para o teste real.

### 🔍 Pesquisa Profunda e Geração de Ideias
• **Pesquisa Abrangente e Revisão de Literatura**: Realize exploração profunda de tópicos com análise sistemática. Identifique padrões, conecte conceitos relacionados entre disciplinas e sintetize descobertas de pesquisa existentes.<br>
• **Descoberta de Insights Inovadores**: Gere materiais de aprendizado estruturados e descubra lacunas de conhecimento. Identifique novas direções de pesquisa promissoras através de síntese inteligente de conhecimento entre domínios.

---

<div align="center">
  <img src="../../assets/figs/title_gradient.svg" alt="All-in-One Tutoring System" width="70%">
</div>

<br>

<!-- ━━━━━━━━━━━━━━━━ Core Learning Experience ━━━━━━━━━━━━━━━━ -->

<table>
<tr>
<td width="50%" align="center" valign="top">

<h3>📚 Q&A de Conhecimento de Documentos Massivos</h3>
<a href="#problem-solving-agent">
<img src="../../assets/gifs/solve.gif" width="100%">
</a>
<br>
<sub>Resolução de Problemas Multi-Agente com Citações Exatas</sub>

</td>
<td width="50%" align="center" valign="top">

<h3>🎨 Visualização de Aprendizado Interativo</h3>
<a href="#guided-learning">
<img src="../../assets/gifs/guided-learning.gif" width="100%">
</a>
<br>
<sub>Explicações Visuais Passo a Passo com Q&A Personalizado</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Practice & Reinforcement ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🎯 Reforço de Conhecimento</h3>

<table>
<tr>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-1.gif" width="100%">
</a>

**Questões Personalizadas**  
<sub>Geração de Questões de Prática Auto-Validadas</sub>

</td>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-2.gif" width="100%">
</a>

**Questões de Imitação**  
<sub>Clonar Estilo de Exame para Prática Autêntica</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Research & Creation ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🔍 Pesquisa Profunda e Geração de Ideias</h3>

<table>
<tr>
<td width="33%" align="center">

<a href="#deep-research">
<img src="../../assets/gifs/deepresearch.gif" width="100%">
</a>

**Pesquisa Profunda**  
<sub>Extensão do Conhecimento do Livro Didático com RAG, Web e Busca de Artigos</sub>

</td>
<td width="33%" align="center">

<a href="#idea-generation">
<img src="../../assets/gifs/ideagen.gif" width="100%">
</a>

**IdeaGen Automatizado**  
<sub>Brainstorming Sistemático e Síntese de Conceitos com Fluxo de Trabalho de Duplo Filtro</sub>

</td>
<td width="33%" align="center">

<a href="#co-writer">
<img src="../../assets/gifs/co-writer.gif" width="100%">
</a>

**IdeaGen Interativo**  
<sub>Co-Writer Alimentado por RAG e Busca Web com Geração de Podcasts</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Knowledge Infrastructure ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🏗️ Sistema de Conhecimento Tudo-em-Um</h3>

<table>
<tr>
<td width="50%" align="center">

<a href="#dashboard--knowledge-base-management">
<img src="../../assets/gifs/knowledge_bases.png" width="100%">
</a>

**Base de Conhecimento Pessoal**  
<sub>Construa e Organize Seu Próprio Repositório de Conhecimento</sub>

</td>
<td width="50%" align="center">

<a href="#notebook">
<img src="../../assets/gifs/notebooks.png" width="100%">
</a>

**Caderno Pessoal**  
<sub>Sua Memória Contextual para Sessões de Aprendizado</sub>

</td>
</tr>
</table>

<p align="center">
  <sub>🌙 Use DeepTutor no <b>Modo Escuro</b>!</sub>
</p>

<details>
<summary><b>Arquitetura do Sistema</b></summary>
<br>

![DeepTutor Full-Stack Workflow](../../assets/figs/full-pipe.png)

</details>

## 📋 Tarefas Pendentes

> Siga-nos para nossas futuras atualizações!
- [ ] Suporte para serviços LLM locais (ex. ollama)
- [ ] Refatoração do módulo RAG (ver [Discussions](https://github.com/HKUDS/DeepTutor/discussions))
- [ ] Codificação profunda a partir da geração de ideias
- [ ] Interação personalizada com o caderno

## 🚀 Início Rápido

### Passo 1: Clonar e Criar Ambiente Virtual

```bash
# Clonar o repositório
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Criar ambiente virtual (escolha um método)

# Opção A: Usar conda (Recomendado)
conda create -n deeptutor python=3.10
conda activate deeptutor

# Opção B: Usar venv
python -m venv venv
# No Windows:
venv\Scripts\activate
# No macOS/Linux:
source venv/bin/activate
```

### Passo 2: Instalar Dependências

Execute o script de instalação com um clique para instalar automaticamente todas as dependências:

```bash
# Recomendado: Usar script bash
bash scripts/install_all.sh

# Alternativa: Usar script Python
python scripts/install_all.py

# Nota: O instalador detecta conda/venv para isolamento. Se nenhum ambiente isolado for detectado, exibirá um aviso mas continuará a instalação.

# Ou instalar manualmente
pip install -r requirements.txt
npm install
```

### Passo 3: Configurar Variáveis de Ambiente

Crie um arquivo `.env` no diretório raiz do projeto baseado em `.env.example`:

```bash
# Copiar do modelo .env.example (se existir)
cp .env.example .env

# Depois edite o arquivo .env com suas chaves de API:
```

### Passo 4: Configurar Portas *(Opcional)*

Por padrão, a aplicação usa:
- **Backend (FastAPI)**: `8001`
- **Frontend (Next.js)**: `3782`

Você pode modificar essas portas em `config/main.yaml` editando os valores `server.backend_port` e `server.frontend_port`.

### Passo 5: Usar Nossas Demos *(Opcional)*

Para experimentar rapidamente nosso sistema, fornecemos duas bases de conhecimento pré-processadas junto com uma coleção de questões desafiadoras e exemplos de uso.

<details>
<summary><b>Coleção de Artigos de Pesquisa</b> — 5 artigos (20-50 páginas cada)</summary>

Uma coleção selecionada de 5 artigos de pesquisa nos campos RAG e Agent do nosso laboratório. Esta demo representa cenários com **ampla cobertura de conhecimento** para fins de pesquisa.

**Artigos Utilizados**: [AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [AutoAgent](https://github.com/HKUDS/AutoAgent) | [RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [LightRAG](https://github.com/HKUDS/LightRAG) | [VideoRAG](https://github.com/HKUDS/VideoRAG)

</details>

<details>
<summary><b>Livro Didático de Ciência de Dados</b> — 8 capítulos, 296 páginas</summary>

Um livro didático de ciência de dados abrangente e desafiador. Esta demo representa cenários com **profundidade de conhecimento profunda** para fins de aprendizado.

**Link do Livro**: [Deep Representation Learning Book](https://ma-lab-berkeley.github.io/deep-representation-learning-book/)
</details>

<br>

**Baixar e Configurar:**

1. Baixe o pacote de demonstração de: [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing)
2. Extraia os arquivos compactados diretamente no diretório `data/`
3. As bases de conhecimento estarão automaticamente disponíveis no sistema após iniciar o projeto

> **Nota:** Usamos `text-embedding-3-large` como modelo de incorporação ao inicializar nossas bases de conhecimento, com `dimensions = 3072`. Certifique-se de que as dimensões do seu modelo de incorporação também sejam 3072.

### Passo 6: Iniciar a Aplicação

```bash
# Certifique-se de que o ambiente virtual está ativado
conda activate deeptutor  # ou: source venv/bin/activate

# Iniciar interface web (frontend + backend)
python scripts/start_web.py

# Ou iniciar apenas a interface CLI
python scripts/start.py

# Para parar o serviço, pressione Ctrl+C
```

### Passo 7: Criar Sua Própria Base de Conhecimento

Após iniciar a aplicação, você pode criar sua própria base de conhecimento através da interface web, em qualquer modalidade.

1. **Acessar a Página de Base de Conhecimento**: Visite http://localhost:{frontend_port}/knowledge
2. **Criar Nova Base de Conhecimento**: Clique no botão "New Knowledge Base"
3. **Nomear Sua Base de Conhecimento**: Digite um nome único para sua base de conhecimento
4. **Fazer Upload de Arquivos**: Faça upload de um ou vários arquivos
5. **Aguardar Processamento**: O sistema processará automaticamente seus arquivos em segundo plano
   - Monitore o progresso da criação no terminal onde `start_web.py` está em execução
   - A base de conhecimento estará disponível assim que o processamento terminar

> **Dicas:** Arquivos grandes podem levar vários minutos para processar. Você pode fazer upload de vários arquivos de uma vez para processamento em lote.

### URLs de Acesso

| Serviço | URL | Descrição |
|:---:|:---|:---|
| **Frontend** | http://localhost:{frontend_port} | Interface web principal |
| **Documentação API** | http://localhost:{backend_port}/docs | Documentação de API interativa |
| **Saúde** | http://localhost:{backend_port}/api/v1/knowledge/health | Verificação de saúde do sistema |

---

## 📂 Armazenamento de Dados

Todo o conteúdo gerado pelo usuário e os dados do sistema são armazenados na pasta `data/`:

```
data/
├── knowledge_bases/              # Armazenamento da base de conhecimento
└── user/                         # Dados de atividade do usuário
    ├── solve/                    # Resultados de resolução de problemas e artefatos
    ├── question/                 # Questões geradas
    ├── research/                 # Relatórios de pesquisa e cache
    ├── co-writer/                # Documentos Co-Writer e arquivos de áudio
    ├── notebook/                 # Registros de caderno e metadados
    ├── guide/                    # Sessões de aprendizado guiado
    ├── logs/                     # Logs do sistema
    └── run_code_workspace/       # Espaço de trabalho de execução de código
```

Todos os resultados são automaticamente salvos quando você realiza qualquer atividade. As pastas são criadas automaticamente se não existirem.

---

## 📖 Documentação dos Módulos

<table>
<tr>
<td align="center"><a href="../../config/README.md">Configuração</a></td>
<td align="center"><a href="../../data/README.md">Repositório de Dados</a></td>
<td align="center"><a href="../../src/api/README.md">Backend API</a></td>
<td align="center"><a href="../../src/core/README.md">Utilitários Principais</a></td>
</tr>
<tr>
<td align="center"><a href="../../src/knowledge/README.md">Base de Conhecimento</a></td>
<td align="center"><a href="../../src/tools/README.md">Ferramentas</a></td>
<td align="center"><a href="../../web/README.md">Frontend Web</a></td>
<td align="center"><a href="../../src/agents/solve/README.md">Módulo de Resolução</a></td>
</tr>
<tr>
<td align="center"><a href="../../src/agents/question/README.md">Módulo de Questões</a></td>
<td align="center"><a href="../../src/agents/research/README.md">Módulo de Pesquisa</a></td>
<td align="center"><a href="../../src/agents/co_writer/README.md">Módulo Co-Writer</a></td>
<td align="center"><a href="../../src/agents/guide/README.md">Módulo de Guia</a></td>
</tr>
<tr>
<td align="center" colspan="4"><a href="../../src/agents/ideagen/README.md">Módulo de Geração de Ideias</a></td>
</tr>
</table>

---

## ❓ Perguntas Frequentes

<details>
<summary><b>O backend não inicia?</b></summary>

**Lista de Verificação**
- Confirme que a versão Python >= 3.10
- Confirme que todas as dependências estão instaladas: `pip install -r requirements.txt`
- Verifique se a porta 8001 está em uso (configurável em `config/main.yaml`)
- Verifique a configuração do arquivo `.env`

**Soluções**
- **Mudar porta**: Edite `config/main.yaml` server.backend_port
- **Verificar logs**: Revise as mensagens de erro do terminal

</details>

<details>
<summary><b>Porta ocupada após Ctrl+C?</b></summary>

**Problema**

Após pressionar Ctrl+C durante uma tarefa em execução (por exemplo, pesquisa profunda), reiniciar mostra erro "porta já em uso".

**Causa**

Ctrl+C às vezes termina apenas o processo frontend enquanto o backend continua executando em segundo plano.

**Solução**

```bash
# macOS/Linux: Encontrar e matar o processo
lsof -i :8001
kill -9 <PID>

# Windows: Encontrar e matar o processo
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```

Depois reinicie o serviço com `python scripts/start_web.py`.

</details>

<details>
<summary><b>Erro "npm: command not found"?</b></summary>

**Problema**

Executar `scripts/start_web.py` mostra `npm: command not found` ou código de saída 127.

**Lista de Verificação**
- Verifique se npm está instalado: `npm --version`
- Verifique se Node.js está instalado: `node --version`
- Confirme que o ambiente conda está ativado (se estiver usando conda)

**Soluções**
```bash
# Opção A: Usar Conda (Recomendado)
conda install -c conda-forge nodejs

# Opção B: Usar instalador oficial
# Baixar de https://nodejs.org/

# Opção C: Usar nvm
nvm install 18
nvm use 18
```

**Verificar Instalação**
```bash
node --version  # Deve mostrar v18.x.x ou superior
npm --version   # Deve mostrar o número da versão
```

</details>

<details>
<summary><b>O frontend não consegue conectar ao backend?</b></summary>

**Lista de Verificação**
- Confirme que o backend está em execução (visite http://localhost:8001/docs)
- Verifique o console do navegador para mensagens de erro

**Solução**

Crie `.env.local` no diretório `web`:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

</details>

<details>
<summary><b>Falha na conexão WebSocket?</b></summary>

**Lista de Verificação**
- Confirme que o backend está em execução
- Verifique as configurações do firewall
- Confirme que a URL WebSocket está correta

**Solução**
- **Verifique os logs do backend**
- **Confirme o formato da URL**: `ws://localhost:8001/api/v1/...`

</details>

<details>
<summary><b>Onde as saídas do módulo são armazenadas?</b></summary>

| Módulo | Caminho de Saída |
|:---:|:---|
| Resolver | `data/user/solve/solve_YYYYMMDD_HHMMSS/` |
| Questão | `data/user/question/question_YYYYMMDD_HHMMSS/` |
| Pesquisa | `data/user/research/reports/` |
| Co-Writer | `data/user/co-writer/` |
| Caderno | `data/user/notebook/` |
| Guia | `data/user/guide/session_{session_id}.json` |
| Logs | `data/user/logs/` |

</details>

<details>
<summary><b>Como adicionar uma nova base de conhecimento?</b></summary>

**Interface Web**
1. Visite http://localhost:{frontend_port}/knowledge
2. Clique em "New Knowledge Base"
3. Digite o nome da base de conhecimento
4. Faça upload de documentos PDF/TXT/MD
5. O sistema processará os documentos em segundo plano

**CLI**
```bash
python -m src.knowledge.start_kb init <kb_name> --docs <pdf_path>
```

</details>

<details>
<summary><b>Como adicionar documentos incrementalmente a uma BC existente?</b></summary>

**CLI (Recomendado)**
```bash
python -m src.knowledge.add_documents <kb_name> --docs <new_document.pdf>
```

**Benefícios**
- Processa apenas novos documentos, economiza tempo e custo da API
- Fusão automática com o grafo de conhecimento existente
- Preserva todos os dados existentes

</details>

<details>
<summary><b>Erro uvloop.Loop ao extrair elementos numerados?</b></summary>

**Problema**

Ao inicializar uma base de conhecimento, você pode encontrar este erro:
```
ValueError: Can't patch loop of type <class 'uvloop.Loop'>
```

Isso ocorre porque Uvicorn usa o loop de eventos `uvloop` por padrão, que é incompatível com `nest_asyncio`.

**Solução**

Use um dos seguintes métodos para extrair elementos numerados:

```bash
# Opção 1: Usar script shell (recomendado)
./scripts/extract_numbered_items.sh <kb_name>

# Opção 2: Comando Python direto
python src/knowledge/extract_numbered_items.py --kb <kb_name> --base-dir ./data/knowledge_bases
```

Isso extrairá elementos numerados (Definições, Teoremas, Equações, etc.) da sua base de conhecimento sem reinicializá-la.

</details>

<br>

---

## 📄 Licença

Este projeto está licenciado sob **[AGPL-3.0](LICENSE)**.


## ⭐ Histórico de Stars

<div align="center">
<a href="https://star-history.com/#HKUDS/DeepTutor&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
 </picture>
</a>
</div>


## 🤝 Contribuição

Acolhemos contribuições da comunidade! Para garantir qualidade e consistência do código, siga as diretrizes abaixo.

<details>
<summary><b>Configuração de Desenvolvimento</b></summary>

### Configuração dos Pre-commit Hooks

Este projeto usa **pre-commit hooks** para formatar automaticamente o código e verificar problemas antes de fazer commit.

**Passo 1: Instalar pre-commit**
```bash
# Usar pip
pip install pre-commit

# Ou usar conda
conda install -c conda-forge pre-commit
```

**Passo 2: Instalar os hooks do Git**
```bash
cd DeepTutor
pre-commit install
```

**Passo 3: (Opcional) Executar verificações em todos os arquivos**
```bash
pre-commit run --all-files
```

Sempre que você executar `git commit`, os pre-commit hooks executarão automaticamente:
- Formatar o código Python com Ruff
- Formatar o código frontend com Prettier
- Verificar erros de sintaxe
- Validar arquivos YAML/JSON
- Detectar problemas de segurança potenciais

### Ferramentas de Qualidade de Código

| Ferramenta | Objetivo | Configuração |
|:---:|:---|:---:|
| **Ruff** | Verificação e formatação do código Python | `pyproject.toml` |
| **Prettier** | Formatação do código frontend | `web/.prettierrc.json` |
| **detect-secrets** | Verificação de segurança | `.secrets.baseline` |

> **Nota**: O projeto usa **Ruff format** em vez de Black para evitar conflitos de formatação.

### Comandos Comuns

```bash
# Commit normal (os hooks são executados automaticamente)
git commit -m "Sua mensagem de commit"

# Verificar manualmente todos os arquivos
pre-commit run --all-files

# Atualizar os hooks para as versões mais recentes
pre-commit autoupdate

# Ignorar os hooks (não recomendado, apenas para emergências)
git commit --no-verify -m "Correção de emergência"
```

</details>

### Diretrizes de Contribuição

1. **Fork e Clone**: Faça fork do repositório e clone-o
2. **Criar uma Branch**: Crie uma branch de funcionalidade a partir de `main`
3. **Instalar Pre-commit**: Siga as etapas de configuração acima
4. **Fazer Modificações**: Escreva código seguindo o estilo do projeto
5. **Testar**: Certifique-se de que suas modificações funcionam corretamente
6. **Commit**: Os pre-commit hooks formatarão automaticamente seu código
7. **Push e PR**: Faça push para seu fork e crie uma Pull Request

### Reportar Problemas

- Use GitHub Issues para reportar bugs ou sugerir funcionalidades
- Forneça informações detalhadas sobre o problema
- Se for um bug, inclua as etapas para reproduzi-lo

<div align="center">
<br>
❤️ Agradecemos a todos os nossos contribuidores por suas valiosas contribuições.

</div>

## 🔗 Projetos Relacionados

<div align="center">

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🎨 RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [💻 DeepCode](https://github.com/HKUDS/DeepCode) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) |
|:---:|:---:|:---:|:---:|
| RAG Simples e Rápido | RAG Multimodal | Assistente de Código IA | Automação de Pesquisa |

**[Laboratório de Inteligência de Dados @ HKU](https://github.com/HKUDS)**

[⭐ Siga-nos](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Reportar um bug](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussões](https://github.com/HKUDS/DeepTutor/discussions)

---
*✨ Obrigado por visitar **DeepTutor**!*

<img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">

</div>
