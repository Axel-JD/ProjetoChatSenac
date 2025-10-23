# app.py — Conecta Senac • Aprendiz
# Versão Final Completa e Otimizada
# ----------------------------------------------------------------------
# Recursos: STT/Voz, Foco Senac, Leitura de Notícias (Trafilatura),
# Filtros de Relevância e Data, UI de Chat Otimizada, Barra de Input Fixa e Estilizada.
# CORREÇÃO: CSS para botões de sugestão com altura igual.
# ----------------------------------------------------------------------

import os
import re
import json
import base64
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import io
import tempfile 

import streamlit as st
import streamlit.components.v1 as components

# =========================
# CONFIG / ASSETS
# =========================
APP_TITLE = "Conecta Senac — Aprendiz"
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = ASSETS_DIR
OUTBOX_DIR = Path("respostas")

def ensure_dir(p: Path) -> None:
    try:
        p.mkdir(exist_ok=True, parents=True)
    except Exception:
        pass

ensure_dir(OUTBOX_DIR)

def _first_existing(*paths: str) -> Optional[str]:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None

def _file_to_b64(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

FAVICON_ICO = os.path.join(ASSETS_DIR, "favicon.ico")
FAVICON_PNG = os.path.join(ASSETS_DIR, "favicon.png")
PAGE_ICON = _first_existing(FAVICON_ICO, FAVICON_PNG) or "🎓"

st.set_page_config(page_title=APP_TITLE, page_icon=PAGE_ICON,
                   layout="centered", initial_sidebar_state="collapsed")
_rerun = (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)

# =========================
# SECRETS / HELPERS
# =========================
def _get_secret(*keys, default: str = "") -> str:
    try:
        cur = st.secrets
        for k in keys:
            cur = cur[k]
        return str(cur).strip()
    except Exception:
        return os.getenv("_".join(keys).upper()) or default

# =========================
# PROVEDORES (LLM + BUSCA + STT)
# =========================
API_KEY = _get_secret("openai", "api_key")
OPENAI_MODEL = _get_secret("openai", "model", default="gpt-4o-mini")
TAVILY_KEY = _get_secret("tavily", "api_key")

llm_client = None
if API_KEY:
    try:
        from openai import OpenAI
        llm_client = OpenAI(api_key=API_KEY)
    except Exception as e:
        pass 

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

# COMPONENTE STT MAIS ESTÁVEL: audio-recorder-streamlit
try:
    from audio_recorder_streamlit import audio_recorder
    HAS_STT = True
except Exception:
    HAS_STT = False
    
# Imports para scraping (leitura) de artigos/notícias
try:
    import requests
    from trafilatura import fetch_url, extract
    HAS_SCRAPER = True
except Exception:
    HAS_SCRAPER = False
    requests = None
    fetch_url = None
    extract = None
    
# =========================
# ESTADO
# =========================
if "hist" not in st.session_state:
    st.session_state.hist: List[Tuple] = [
        ("bot",
         "Olá! Eu sou o **Aprendiz**, do **Conecta Senac**. Posso conversar sobre cursos, inscrições, EAD, unidades e também sobre como eu funciono. Como posso te ajudar?",
         "feliz",
         None)
    ]
if "awaiting_location" not in st.session_state:
    st.session_state.awaiting_location = False
if "awaiting_contact" not in st.session_state:
    st.session_state.awaiting_contact = False 
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False
if "font_size" not in st.session_state:
    st.session_state.font_size = 1.0
if "avatars" not in st.session_state:
    st.session_state.avatars = {}
if "tts_enabled" not in st.session_state:
    st.session_state.tts_enabled = False
if "stt_enabled" not in st.session_state:
    st.session_state.stt_enabled = True

# =========================
# AVATARES
# =========================
def _load_image(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

@st.cache_data(show_spinner=False)
def carregar_avatars_cached(avatar_dir: str) -> dict:
    nomes = ["feliz", "neutro", "pensando", "triste", "duvida"]
    avatars = {}
    for n in nomes:
        caminho = os.path.join(avatar_dir, f"{n}.png")
        if os.path.exists(caminho):
            img = _load_image(caminho)
            if img:
                avatars[n] = img
    return avatars

if not st.session_state.get("avatars"):
    st.session_state.avatars = carregar_avatars_cached(AVATAR_DIR)

def avatar_img(emocao: str) -> str:
    avatars = st.session_state.get("avatars", {})
    b64img = avatars.get(emocao)
    if not b64img:
        return "<div class='avatar-emoji'>🎓</div>"
    return f"""<img class='avatar-img' src="data:image/png;base64,{b64img}" alt="{emocao}"/>"""

# =========================
# SIDEBAR
# =========================
with st.sidebar:
    st.header("⚙️ Preferências")
    st.session_state.dark_mode = st.toggle("🌙 Modo escuro", value=st.session_state.dark_mode)
    st.session_state.tts_enabled = st.toggle("🔊 Ler respostas em voz alta", value=st.session_state.tts_enabled)
    st.session_state.stt_enabled = st.toggle("🎤 Entrada por voz (microfone)", value=st.session_state.stt_enabled)
    st.session_state.font_size = st.slider("♿ Tamanho da fonte", 1.0, 1.5, st.session_state.font_size, 0.05)
    temperature = st.slider("Criatividade (temperature)", 0.0, 1.0, 0.35, 0.05, key="temperature")
    web_toggle = st.toggle("🔎 Ativar pesquisa web quando fizer sentido", value=True)
    st.caption(f"LLM: {'OpenAI' if llm_client else '⚠️ não configurado'}")
    st.caption(f"Busca: {'Tavily' if TAVILY_KEY else ('DDGS' if DDGS else '⚠️ indisponível')}")
    
    # Diagnóstico e instrução
    st.caption(f"Status do Áudio: {'Sucesso' if HAS_STT else 'FALHA'}")
    if st.session_state.stt_enabled and not HAS_STT:
        st.error("Falha ao carregar o componente de microfone. Verifique o requirements.txt.")
    
    # Diagnóstico do Scraper
    if web_toggle and not HAS_SCRAPER:
        st.warning("Libs 'requests' ou 'trafilatura' não econtradas. A leitura de artigos está desativada. Verifique o requirements.txt e packages.txt.")

# =========================
# TEMA / CSS (FUNDO CORRIGIDO)
# =========================
DARK = st.session_state.dark_mode
if DARK:
    COR_BG1, COR_BG2 = "#0b1220", "#0f172a"
    COR_FUNDO = "#0f172a"; COR_BORDA = "#1e3a8a"
    COR_USER = "#1e40af"; COR_USER_TXT = "#e5e7eb" # Texto do usuário (Branco no modo escuro)
    COR_BOT = "#F47920"; COR_BOT_TXT = "#111827"
    COR_LINK = "#93c5fd"; HEADER_GRAD_1, HEADER_GRAD_2 = "#0e4e9b", "#2567c4"
    # Cor das Sugestões
    COR_SUG_BG = COR_USER; COR_SUG_TXT = COR_USER_TXT;
else:
    COR_BG1, COR_BG2 = "#fbfdff", "#eef3fb"
    COR_FUNDO = "#F7F9FC"; COR_BORDA = "#0E4E9B"
    COR_USER = "#0E4E9B"; COR_USER_TXT = "#111827" # Texto do usuário (Preto no modo claro)
    COR_BOT = "#F47920"; COR_BOT_TXT = "#FFFFFF"
    COR_LINK = "#0A66C2"; HEADER_GRAD_1, HEADER_GRAD_2 = "#0e4e9b", "#2567c4"
    # Cor das Sugestões
    COR_SUG_BG = COR_USER; COR_SUG_TXT = COR_USER_TXT;

BASE_FONT_SIZE_REM = 0.985
dynamic_font_size = BASE_FONT_SIZE_REM * st.session_state.font_size

st.markdown(f"""
<style>
:root {{
  --bg1:{COR_BG1}; --bg2:{COR_BG2}; --fundo:{COR_FUNDO}; --borda:{COR_BORDA};
  --user:{COR_USER}; --userTxt:{COR_USER_TXT}; --bot:{COR_BOT}; --botTxt:{COR_BOT_TXT};
  --link:{COR_LINK}; --h1:{HEADER_GRAD_1}; --h2:{HEADER_GRAD_2};
  --sugBg:{COR_SUG_BG}; --sugTxt:{COR_SUG_TXT};
}}
* {{ box-sizing: border-box; }}

/* CORREÇÃO DO MODO ESCURO: Define o background da página e do stApp */
body {{ background-color: var(--bg2); }} 
.stApp {{ background-color: var(--bg2); background-attachment: fixed; }} 
/* FIM DA CORREÇÃO */

.wrap {{ width:100%; max-width:900px; margin:0 auto; }}
.header {{ background: linear-gradient(135deg, var(--h1) 0%, var(--h2) 100%); color:#fff; padding:12px 14px; border-radius:16px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.brand {{ display:flex; align-items:center; gap:12px; }}
.brand h2 {{ margin:0; font-weight:700; letter-spacing:.2px; }}
.tag {{ font-size:12px; background:rgba(255,255,255,.18); padding:4px 10px; border-radius:999px; border:1px solid rgba(255,255,255,.25) }}
.chat-box {{ background:var(--fundo); border:2px solid var(--borda); border-radius:16px; padding:12px; max-height:72vh; overflow-y:auto; box-shadow:0 10px 24px rgba(25,76,145,.08); margin-top:12px; }}
.msg {{ display:inline-block; white-space:pre-wrap; overflow-wrap:anywhere; padding:12px 14px; border-radius:16px; margin:6px 0; max-width:78%; line-height:1.28; font-size:{dynamic_font_size}rem; }}
.msg-user {{ background:var(--user); color:var(--userTxt); margin-left:auto; border-bottom-right-radius:8px; box-shadow:0 6px 16px rgba(14,78,155,.18); }}
.msg-bot {{ background:var(--bot); color:var(--botTxt); margin-right:auto; border-bottom-left-radius:8px; box-shadow:0 6px 16px rgba(244,121,32,.18); }}
.bubble-row {{ display:flex; align-items:flex-end; gap:10px; margin: 8px 0; }}
.avatar-shell {{ flex:0 0 auto; display:flex; align-items:flex-end; width:56px; height:56px; flex-shrink:0; }}
.avatar-img {{ width:56px; height:56px; border-radius:50%; object-fit:cover; box-shadow:0 4px 12px rgba(138,67,0,.16); background-color: white; border: 2px solid var(--bot); }}
.avatar-emoji {{ width:56px; height:56px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#ffd9bf; color:#8a4300; font-size:28px; border: 2px solid var(--bot); }}
.avatar-user {{ width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#cfe3ff; color:#0c3d88; font-size:18px; border: 2px solid var(--user); }}
.typing-bubble {{ background:var(--bot); color:var(--botTxt); margin-right:auto; border-radius:16px; border-bottom-left-radius:8px; padding:10px 14px; display:inline-flex; align-items:center; gap:6px; }}
.dot {{ width:6px; height:6px; border-radius:50%; background:var(--botTxt); opacity:.75; animation: blink 1.4s infinite ease-in-out both; }}
.dot:nth-child(2) {{ animation-delay:.2s; }} .dot:nth-child(3) {{ animation-delay:.4s; }}
@keyframes blink {{ 0%, 80%, 100% {{ transform: scale(0); opacity: .3; }} 40% {{ transform: scale(1); opacity: 1; }} }}
a {{ color:var(--link); text-decoration:none; }} a:hover {{ text-decoration:underline; }}


/* --- INÍCIO DA MUDANÇA: SUGESTÕES RÁPIDAS (COM ALTURA IGUAL) --- */
.sugestoes {{
    margin-top: 10px;
}}
.sugestoes h4 {{
    font-weight: 600;
    color: var(--borda);
    margin-bottom: 6px;
    font-size: 1rem;
}}
/* 1. Faz o contêiner das colunas esticar os filhos */
.sugestoes div[data-testid="stHorizontalBlock"] {{
    display: flex;
    align-items: stretch; /* Faz todas as colunas terem a mesma altura */
}}
/* 2. Faz o contêiner do botão preencher a coluna */
.sugestoes div[data-testid="stButton"] {{
    height: 100%; 
}}
/* 3. Estiliza o botão para preencher o contêiner e parecer o chat do usuário */
div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] button {{
    background-color: var(--sugBg);
    color: var(--sugTxt);
    border: 1px solid rgba(0,0,0,0.1);
    border-radius: 12px;
    height: 100%; /* Preenche a altura do contêiner */
    width: 100%;
    font-size: 0.85rem;
    display: flex;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 10px 5px; /* Adiciona padding interno */
}}
div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] button:hover {{
    background-color: var(--sugBg);
    color: var(--sugTxt);
    opacity: 0.85; 
    border: 1px solid var(--sugBg);
}}
/* --- FIM DA MUDANÇA: SUGESTÕES --- */


/* --- INÍCIO DO CÓDIGO DA BARRA FIXA --- */
.chat-box {{
    padding-bottom: 120px; /* Aumenta o padding para a barra fixa não cobrir a última mensagem */
}}
.input-bar {{
    display: none; /* Oculta o placeholder original */
}}
.fixed-input-container {{
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    background-color: var(--bg2); /* Usa a cor de fundo do tema */
    border-top: 1px solid var(--borda);
    padding: 12px 0px; /* Espaçamento vertical */
    z-index: 999;
    display: flex;
    justify-content: center;
}}
.fixed-input-inner {{
    width: 100%;
    max-width: 900px; /* Mesma largura do .wrap */
    display: flex;
    align-items: center; /* Alinha o input e o botão verticalmente */
    gap: 10px; /* Espaço entre o input e o botão */
    padding: 0 15px; /* Espaçamento lateral */
}}
/* Remove o label (título) do st.text_input */
.fixed-input-inner div[data-testid="stTextInput"] label {{
    display: none;
}}
/* Estiliza o st.text_input com BORDAS SUAVES e Fundo Escuro */
.fixed-input-inner div[data-testid="stTextInput"] > div {{
    border-radius: 25px !important; /* Bordas suaves */
    background-color: var(--fundo); /* Cor de fundo da caixa de chat */
}}
/* Cor do placeholder (ex: "Digite sua mensagem...") */
.fixed-input-inner div[data-testid="stTextInput"] ::-webkit-input-placeholder {{
    color: #999;
}}
/* Cor do texto digitado */
.fixed-input-inner div[data-testid="stTextInput"] input {{
    color: var(--botTxt); /* Usa a cor do texto do bot (preto ou branco) */
}}
/* Hack para o iframe do audio_recorder */
.fixed-input-inner iframe {{
    transform: scale(0.9); /* Ícone um pouco menor */
    height: 50px !important; /* Impede que estique */
    width: 50px !important;
    margin-top: -10px; /* Ajuste fino de alinhamento */
    border: none; /* Remove borda do iframe */
    background: transparent; /* Fundo transparente */
}}
/* Esconde a barra preta feia do audio_recorder */
.fixed-input-inner iframe html body {{
    background: transparent !important;
}}
/* --- FIM DO CÓDIGO DA BARRA FIXA --- */

</style>
""", unsafe_allow_html=True)

st.markdown("<div class='wrap'>", unsafe_allow_html=True)
st.markdown("<div class='header'><div class='brand'><span>🎓</span><h2>Conecta Senac • Aprendiz</h2></div><span class='tag'>conversa natural • foco Senac</span></div>", unsafe_allow_html=True)

# =========================
# SUGESTÕES (on-topic)
# =========================
st.markdown("<div class='sugestoes'><h4>💡 Sugestões rápidas</h4></div>", unsafe_allow_html=True)
SUGESTOES = [
    "Quero saber mais sobre os cursos do Senac",
    "Como funciona a inscrição?",
    "Quais opções EAD existem?",
    "Onde tem uma unidade perto de mim?",
    "Me conte mais sobre você (Aprendiz)"
]
cols = st.columns(len(SUGESTOES))
for i, texto in enumerate(SUGESTOES):
    if cols[i].button(texto, use_container_width=True, key=f"sug_{i}"):
        st.session_state.hist.append(("user", texto, None, None))
        st.session_state.hist.append(("typing", "digitando...", "pensando", None))
        _rerun()

# =========================
# ESCOPO SUAVE (heurístico)
# =========================
SENAC_TERMS = ["senac","senac rs","senacrs","senac.br","senacrs.com.br","curso","cursos",
               "matrícula","matricula","inscrição","inscricao","unidade","unidades","ead",
               "mensalidade","bolsa","certificado","grade","carga","conecta senac","aprendiz"]
SMALLTALK_TERMS = ["aprendiz","conecta senac","assistente","ia","chatbot","sobre você","quem é você",
                   "como funciona","privacidade","dados","projeto"]
AMBIGUOUS_TERMS = ["carreira","emprego","trabalho","currículo","estágio","faculdade","universidade",
                   "enem","vestibular","curso online","curso técnico","tecnologia","gastronomia","gestão","idiomas"]

def classify_scope_heuristic(text: str) -> str:
    t = (text or "").lower()
    if any(term in t for term in SENAC_TERMS): return "on"
    if any(term in t for term in SMALLTALK_TERMS): return "on"
    if any(term in t for term in AMBIGUOUS_TERMS): return "ambiguous"
    return "off"

# =========================
# BUSCA WEB (Tavily → DDGS) + SCRAPING (LEITURA)
# =========================
EXPLICIT_SEARCH_TOKENS = ["pesquise", "pesquisa", "procurar", "procure", "buscar", "busque", "notícia", "notícias", "artigo", "artigos", "ler", "g1", "reportagem", "matéria"]
ADDR_TOKENS = ["onde fica","endereço","endereco","unidade","unidades","localização","localizacao","perto de mim"]
INFO_TOKENS = ["horário","horario","telefone","preço","valor","mensalidade","data","quando","link","site",
               "matrícula","inscrição","inscricao","grade curricular","carga horária","carga horaria"]

def should_search_web(text: str) -> bool:
    t = (text or "").lower()
    if any(tok in t for tok in EXPLICIT_SEARCH_TOKENS): return True
    if any(tok in t for tok in ADDR_TOKENS + INFO_TOKENS):
        if "senac" in t or any(tok in t for tok in ["curso","unidade","matrícula","inscrição","inscricao","ead"]):
            return True
    return False

@st.cache_data(ttl=3600, show_spinner=False) # Cache de 1 hora
def web_search(query: str, max_results: int = 6):
    """Busca web básica (APENAS snippets), com filtro de data para consultas 'recentes'."""
    
    l_query = query.lower()
    is_news_query = any(tok in l_query for tok in ["notícia", "notícias", "artigo", "artigos", "g1", "reportagem", "matéria"])

    # 1. Define palavras-chave que ativam o filtro de data
    RECENT_KEYWORDS = ["recente", "recentes", "última", "últimas", "agora", "hoje", "esta semana", "este mês"]
    is_recent_query = any(tok in l_query for tok in RECENT_KEYWORDS)
    
    # 2. Define o limite de tempo (ex: '1m' para último mês) se for uma busca recente
    tavily_time_range = "1m" if is_recent_query else None # Tavily: '1m' = último mês
    ddgs_timelimit = "m" if is_recent_query else None   # DDGS: 'm' = último mês
    
    # Lógica de consulta (que já alteramos antes)
    if "senac" in l_query:
        # A consulta já menciona "senac". Pesquise em toda a web. (Ex: "notícias senac g1")
        q = query
    elif is_news_query:
        # A consulta é sobre notícias, mas não menciona "senac". Adicione "Senac" e pesquise em toda a web.
        # (Ex: "notícias no g1" -> "Senac notícias no g1")
        q = f"Senac {query}"
    else:
        # Consulta geral (cursos, horários, etc.). Restrinja aos sites do Senac.
        q = f"site:senacrs.com.br OR site:senac.br {query}"
    

    if TAVILY_KEY:
        try:
            from tavily import TavilyClient
            tv = TavilyClient(api_key=TAVILY_KEY)
            
            # Adiciona o parâmetro 'time_range' à chamada da API
            res = tv.search(
                query=q, 
                max_results=max_results, 
                search_depth="basic",
                time_range=tavily_time_range # <--- PARÂMETRO ADICIONADO
            )

            if isinstance(res, dict) and res.get("results"):
                return [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content")} for r in res["results"]]
        except Exception:
            pass
            
    if DDGS is None: return []
    try:
        hits = []
        with DDGS() as ddgs:
            
            # Adiciona o parâmetro 'timelimit' à chamada da API
            ddgs_results = ddgs.text(
                q, 
                max_results=max_results,
                timelimit=ddgs_timelimit # <--- PARÂMETRO ADICIONADO
            )

            for r in ddgs_results:
                hits.append({"title": r.get("title"), "url": r.get("href") or r.get("url"), "content": r.get("body")})
        return hits
    except Exception:
        return []

# Função helper para "ler" o conteúdo de artigos/notícias
@st.cache_data(ttl=3600, show_spinner=False)
def scrape_article_text(url: str) -> Optional[str]:
    """Tenta baixar e extrair o texto principal de uma URL usando Trafilatura."""
    if not url or not HAS_SCRAPER:
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        response.raise_for_status() 
        
        main_text = extract(response.content, 
                            include_comments=False, 
                            include_tables=False,
                            no_fallback=True)
        
        return (main_text or "").strip()
    except Exception as e:
        return None # Falha silenciosa

# Função principal para buscar E ler artigos
@st.cache_data(ttl=3600, show_spinner=False)
def search_and_read_articles(query: str, max_results: int = 4):
    """Busca na web, FILTRA, e depois tenta 'ler' cada resultado."""
    
    # 1. Busca básica (links e snippets)
    # Pede 2 resultados a mais para ter uma margem para o filtro
    basic_results = web_search(query, max_results + 2) 
    if not basic_results:
        return []
        
    # 2. Filtra os resultados para garantir que sejam sobre "Senac"
    filtered_results = []
    for r in basic_results:
        title = (r.get("title") or "").lower()
        url = (r.get("url") or "").lower()
        
        # Só mantém o resultado se "senac" estiver no título ou na URL
        if "senac" in title or "senac" in url:
            filtered_results.append(r)
    
    # Se o filtro removeu tudo, retorne vazio
    if not filtered_results:
        return []

    # 3. Tenta ler cada URL FILTRADA
    advanced_results = []
    # Itera sobre 'filtered_results' e limita aos 'max_results' originais
    for r in filtered_results[:max_results]: 
        snippet = r.get("content") or ""
        url = r.get("url")
        full_content = scrape_article_text(url)
        
        final_content = full_content if (full_content and len(full_content) > len(snippet) * 1.5) else snippet
        
        advanced_results.append({
            "title": r.get("title"),
            "url": url,
            "content": final_content
        })
    return advanced_results

# =========================
# PROMPTS / LLM (sempre JSON)
# =========================
BASE_SISTEMA = (
    "Você é o Aprendiz, assistente do projeto Conecta Senac. Converse de forma natural, gentil e útil (PT-BR). "
    "Seu tom deve ser **sempre prestativo e positivo**. Dê preferência à emoção 'feliz' em suas respostas, a menos que o usuário esteja claramente frustrado ou confuso. "
    "Seu foco ABSOLUTO é no Senac (especialmente Senac RS), seus cursos/serviços, inscrições, EAD/presencial, unidades/endereços/horários, eventos, **notícias** e no próprio Aprendiz/Conecta Senac (small talk permitido). "
    
    "Se a pergunta for alheia (ex: política, esportes) E **nenhum contexto de busca for fornecido**, você DEVE **redirecionar** ou **conectar** o assunto ao Senac. (Ex: 'Você me perguntou sobre [Assunto Geral], mas o Senac tem [Curso Relacionado].') "
    
    "Quando o usuário pedir por **notícias ou artigos** (ex: 'notícias do senac', 'resumo da notícia'), e o contexto da web for fornecido (com 'content' e 'url'), sua resposta DEVE seguir este formato:"
    "1.  Responda diretamente (ex: 'Sim, encontrei esta notícia...')."
    "2.  Forneça um **breve resumo** do artigo com base no texto lido (o 'content' do contexto)."
    "3.  Formate o link da fonte principal em markdown, assim: **[Título da Notícia](link.com)**."
    "NÃO liste links irrelevantes se eles não responderem à pergunta sobre a notícia."

    "Se o usuário demonstrar interesse (ex: 'Quero me inscrever', 'Me diga o próximo passo', 'Gostei e quero mais'), a próxima resposta DEVE ser uma pergunta para ele, verificando se você pode pegar o NOME e E-MAIL dele e armazenar para que o Senac entre em contato. "
    "Use os dados da web (contexto) quando fornecidos. O contexto pode conter o TEXTO COMPLETO de artigos/notícias. **Responda a pergunta do usuário com base nesse contexto.** "
    "Para endereços/unidades, NUNCA adivinhe: peça a cidade se faltar; se houver fontes, cite links. "
    "Formate ESTRITAMENTE como JSON válido (sem texto fora do JSON): "
    '{"emotion":"feliz|neutro|triste|duvida","content":"<markdown conciso>"}'
)

def _slugify(text: str, maxlen: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+","-", text).strip("-").lower()
    return text[:maxlen] or "resposta"

def _save_json(payload: dict, fontes: Optional[list]) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify((payload.get("content") or "")[:36])
    data = dict(payload); data["sources"] = fontes or []
    path = OUTBOX_DIR / f"{ts}_{slug}.json"
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return path

def _last_msgs(limit_pairs: int = 6) -> List[Dict[str,str]]:
    msgs: List[Dict[str,str]] = []
    temp_hist = [item for item in st.session_state.hist if item[0] in ["user", "bot"]]
    for who, msg, *_ in temp_hist[-(limit_pairs*2):]:
        msgs.append({"role":"user" if who=="user" else "assistant", "content": msg})
    return msgs

def llm_json(messages: List[Dict[str,str]], temperature=0.35, max_tokens=500) -> dict:
    if llm_client is None:
        return {"emotion":"neutro","content":"⚠️ Para respostas completas, configure sua chave da OpenAI em secrets.toml."}
    
    full_messages = [{"role":"system","content": BASE_SISTEMA}] + messages
    
    try:
        response = llm_client.chat.completions.create(
            model=OPENAI_MODEL, 
            messages=full_messages,
            temperature=temperature, 
            max_tokens=max_tokens
        )
        raw_text = (response.choices[0].message.content or "").strip()
    except Exception as e:
        return {"emotion": "triste", "content": f"⚠️ Desculpe, ocorreu um problema técnico ao gerar a resposta: {e}"}

    try:
        match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start_index = raw_text.find('{')
            end_index = raw_text.rfind('}')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_str = raw_text[start_index : end_index + 1]
            else:
                return {"emotion": "feliz", "content": raw_text}
        
        data = json.loads(json_str)
        
        if "content" in data and "emotion" in data:
            return data
        else:
            return {"emotion": "feliz", "content": raw_text}
            
    except (json.JSONDecodeError, IndexError):
        return {"emotion": "feliz", "content": raw_text}

# =========================
# Endereços / cidade
# =========================
def extract_city(text: str) -> str:
    m = re.search(r"senac\s+([a-zçãõáéíóúâêôà\- ]+)", (text or "").lower(), re.IGNORECASE)
    return m.group(1).strip().title() if m else ""

def responder_endereco(cidade: str) -> list:
    q1 = f"site:senacrs.com.br unidades {cidade}"
    q2 = f"site:senac.br unidades {cidade}"
    # Esta função usa a busca BÁSICA (rápida)
    fontes = web_search(q1, 6) or []
    fontes += web_search(q2, 4) or []
    out, seen = [], set()
    for f in fontes:
        url = (f.get("url") or "").strip()
        if not url or url in seen: continue
        seen.add(url); out.append({"title": (f.get("title") or 'Fonte').strip(), "url": url, "content": f.get("content")})
    return out

# =========================
# GERAÇÃO DE RESPOSTA (JSON)
# =========================
def gerar_resposta_json(pergunta: str, temperature: float):
    p = (pergunta or "").strip()
    pl = p.lower()
    fontes: list = []
    msgs = _last_msgs()
    
    # --- BLOCO 1: CAPTURA DE CONTATO (LEAD) ---
    if st.session_state.awaiting_contact:
        st.session_state.awaiting_contact = False
        
        m_email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', p)
        if m_email:
            email = m_email.group(0).lower()
            name_part = p[:m_email.start()].strip()
            name = name_part.split()[-1].title() if name_part else "Interessado"
            
            # Resposta simulada de salvamento
            return {"emotion": "feliz", "content": f"Perfeito, **{name}**! O e-mail **{email}** foi processado. A equipe Senac entrará em contato em breve. Enquanto isso, mais alguma dúvida sobre nossos cursos?"}, []
        else:
            return {"emotion": "duvida", "content": "Não consegui identificar seu e-mail. Por favor, digite seu **NOME** e **E-MAIL** para contato, ou diga 'Não' se não quiser prosseguir."}, []
    
    # --- BLOCO 2: INÍCIO DA CAPTURA (GATILHO) ---
    if any(k in pl for k in ["quero me inscrever", "proximo passo", "como me inscrevo", "gostei e quero mais", "quero começar"]):
        st.session_state.awaiting_contact = True
        return {"emotion": "feliz", "content": "Excelente! Posso te ajudar com o processo. Para agilizar seu atendimento com um consultor do Senac, você me autoriza a registrar seu nome e e-mail?"}, []

    # --- BLOCO 3: LOCALIZAÇÃO DE UNIDADE (SE NECESSÁRIO) ---
    if any(tok in pl for tok in ["onde fica","endereço","endereco","unidade","unidades","localização","localizacao","perto de mim"]):
        city = extract_city(p)
        if not city:
            st.session_state.awaiting_location = True
            return {"emotion":"feliz","content":"Para localizar certinho, me diz a **cidade** (e o estado, se for fora do RS). 😉"}, []
        else:
            if web_toggle:
                fontes = responder_endereco(city) # Usa a busca BÁSICA

    if st.session_state.awaiting_location and not any(k in pl for k in ["senac","curso","inscri","pagamento","unidade","matrícula","ead"]):
        st.session_state.awaiting_location = False
        city = p.title()
        if web_toggle:
            fontes = responder_endereco(city) # Usa a busca BÁSICA
        
        if fontes:
            ctx = "\n".join([f"[{i+1}] {h['title']} — {h['url']}\n{(h.get('content') or '')[:600]}" for i,h in enumerate(fontes)])
            msgs.insert(0, {"role":"system","content":"Contexto de pesquisa:\n"+ctx})
        msgs.append({"role":"user","content": f"O usuário informou a cidade: {city}. Oriente sem inventar e cite links confiáveis se possível."})
        payload = llm_json(msgs, temperature=temperature)
        return payload, fontes

    # --- BLOCO 4: GATILHO DE REDIRECIONAMENTO (FORÇAR FOCO) ---
    scope = classify_scope_heuristic(p)
    
    if scope == "off":
        msgs.insert(0, {"role":"system",
                        "content": f"A pergunta do usuário '{p}' está fora do escopo Senac. Você DEVE usar a sua resposta para gentilmente redirecionar ou conectar o assunto ao contexto de cursos/serviços do Senac. **Exemplo:** 'Vi que você perguntou sobre [Assunto]. O Senac oferece [Curso Relacionado] que pode te ajudar. Fale mais sobre isso!'"
                       })
    elif scope == "ambiguous":
        msgs.insert(0, {"role":"system",
                        "content": "A pergunta é geral (carreira, tecnologia, etc.); conecte naturalmente ao contexto do Senac/Conecta Senac/Aprendiz, dando ênfase a cursos relevantes."
                       })

    # --- BLOCO 5: BUSCA WEB E RESPOSTA FINAL ---
    # (Só roda se 'fontes' não foi preenchido pelo Bloco 3)
    if not fontes and web_toggle and should_search_web(p):
        fontes = search_and_read_articles(p, 5) # Chama a nova função de LEITURA

    if fontes:
        # Trunca o conteúdo (que pode ser longo) antes de enviar ao LLM
        ctx = "\n".join([f"[{i+1}] {h['title']} — {h['url']}\n{(h.get('content') or '')[:1500]}" for i,h in enumerate(fontes)])
        msgs.insert(0, {"role":"system","content":"Contexto de pesquisa:\n"+ctx})
        
    msgs.append({"role":"user","content": p})

    payload = llm_json(msgs, temperature=temperature)
    return payload, fontes

# =========================
# CHAT UI
# =========================
st.markdown("<div id='chat' class='chat-box'>", unsafe_allow_html=True)

for who, msg, emo, fontes in st.session_state.hist:
    if who == "user":
        st.markdown(
            "<div class='bubble-row' style='justify-content:flex-end;'>"
            f"<div class='msg msg-user'>{msg}</div>"
            "<div class='avatar-user'>🧑</div>"
            "</div>",
            unsafe_allow_html=True
        )
    elif who == "typing":
        st.markdown(
            "<div class='bubble-row' style='justify-content:flex-start;'>"
            f"<div class='avatar-shell'>{avatar_img('pensando')}</div>"
            "<div class='typing-bubble'><div class='dot'></div><div class='dot'></div><div class='dot'></div></div>"
            "</div>",
            unsafe_allow_html=True
        )
    else:
        emotion = emo if emo and emo in st.session_state.avatars else 'feliz'
        st.markdown(
            "<div class='bubble-row' style='justify-content:flex-start;'>"
            f"<div class='avatar-shell'>{avatar_img(emotion)}</div>"
            f"<div class='msg msg-bot'>{msg}</div>"
            "</div>",
            unsafe_allow_html=True
        )
        
        # --- LÓGICA INTELIGENTE DE LINKS ---
        # 1. Verifica se a IA já formatou um link de notícia (ex: [Título](http...))
        is_news_response = re.search(r'\[.*?\]\(http.*?\)', msg)
        
        # 2. Só mostre a lista de links se:
        #    a) Houver fontes E
        #    b) NÃO for uma resposta de notícia (para esconder links irrelevantes)
        if fontes and not is_news_response:
            links = "".join([f"<li><a href='{f.get('url','')}' target='_blank'>{f.get('title','Fonte')}</a></li>" for f in fontes if f.get('url')])
            if links:
                st.markdown(f"<ul class='link-list' style='margin:6px 0 10px 50px'>{links}</ul>", unsafe_allow_html=True)
        # --- FIM DA LÓGICA ---

st.markdown("</div>", unsafe_allow_html=True)
components.html("<script>const box=parent.document.querySelector('#chat'); if(box){box.scrollTop=box.scrollHeight;}</script>", height=0)

# =========================
# TTS (texto→fala)
# =========================
def text_to_speech_component(text: str):
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    text = text.replace("`", "").replace(">", "").strip()
    text_js = json.dumps(text)
    components.html(f"""
        <script>
            try {{
                const text = {text_js};
                const u = new SpeechSynthesisUtterance(text);
                u.lang = 'pt-BR';
                speechSynthesis.cancel();
                speechSynthesis.speak(u);
            }} catch (e) {{
                console.warn('TTS indisponível:', e);
            }}
        </script>
    """, height=0)

# =========================
# PROCESSAR "typing"
# =========================
if st.session_state.hist and st.session_state.hist[-1][0] == "typing":
    pergunta = ""
    for who, msg, *_ in reversed(st.session_state.hist[:-1]):
        if who == "user":
            pergunta = msg
            break
            
    payload, fontes = gerar_resposta_json(pergunta, st.session_state.get("temperature", 0.35))
    
    final_content = (payload.get("content") or "Desculpe, não consegui processar a resposta.").strip()
    emotion = payload.get("emotion", "feliz") # Pega a emoção da IA

    # Força a emoção "feliz" se a IA sugerir "neutro"
    if emotion == "neutro":
        emotion = "feliz"

    valid_emotions = ["feliz", "neutro", "pensando", "triste", "duvida"]
    final_emotion = emotion if emotion in valid_emotions else "feliz"
    
    try:
        _ = _save_json({"emotion": final_emotion, "content": final_content}, fontes)
    except Exception:
        pass
        
    st.session_state.hist[-1] = ("bot", final_content or "Posso te ajudar com algo do Senac? 🙂", final_emotion, fontes)
    
    if st.session_state.tts_enabled and final_content:
        text_to_speech_component(final_content)
    
    _rerun()

# =========================
# BARRA DE ENTRADA (FIXA E ESTILIZADA COM CSS)
# =========================

audio_bytes: Optional[bytes] = None
mic_txt: Optional[str] = None
user_msg: Optional[str] = None

# Inicia o contêiner fixo
st.markdown("<div class='fixed-input-container'><div class='fixed-input-inner'>", unsafe_allow_html=True)

# Define as colunas (85% para texto, 15% para botão)
col1, col2 = st.columns([0.85, 0.15])

with col1:
    # 1. st.text_input para a barra com bordas suaves
    user_msg = st.text_input(
        "Digite sua mensagem...", # O label será ocultado pelo CSS
        key="chat_text_input",
        placeholder="Digite sua mensagem..."
    )

with col2:
    # 2. Botão de áudio
    if st.session_state.stt_enabled and HAS_STT:
        # Usamos st.container para aplicar o CSS corretamente
        with st.container():
            audio_bytes = audio_recorder(
                text="", 
                recording_color="#e8612c", 
                neutral_color="#cccccc",
                icon_size="1.5x",
                key="audio_recorder_input"
            )
    else:
        st.write("") # Espaço reservado

# Fecha os contêineres
st.markdown("</div></div>", unsafe_allow_html=True)


# --- LÓGICA DE PROCESSAMENTO (PERMANECE IGUAL) ---

# 3. Lógica de Transcrição
if audio_bytes and llm_client:
    tmp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_file_path = tmp_file.name

        with open(tmp_file_path, "rb") as audio_file:
            with st.spinner("🎧 Transcrevendo áudio..."):
                transcricao_obj = llm_client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file,
                    language="pt"
                )
                mic_txt = transcricao_obj.text
                st.session_state.hist.append(("user", mic_txt, None, None))
                
    except Exception as e:
        mic_txt = "Transcrição falhou: Ocorreu um erro na API Whisper."
        st.error(f"Erro na transcrição Whisper. Verifique sua chave e permissões.")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
            
elif audio_bytes:
     st.error("Chave OpenAI é necessária para transcrever com Whisper.")
     mic_txt = None

# 4. Processamento da Mensagem (Voz ou Texto)
msg_to_process = None

if mic_txt and mic_txt.strip():
    # Mensagem veio da VOZ
    msg_to_process = mic_txt.strip()
    if "chat_text_input" in st.session_state:
        st.session_state.chat_text_input = "" 
elif user_msg and user_msg.strip():
    # Mensagem veio do TEXTO (Enter)
    msg_to_process = user_msg.strip()
    st.session_state.hist.append(("user", msg_to_process, None, None))
    if "chat_text_input" in st.session_state:
        st.session_state.chat_text_input = "" 
    
if msg_to_process:
    st.session_state.hist.append(("typing", "digitando...", "pensando", None))
    _rerun()

# =========================
# RODAPÉ - LIMPO
# =========================
if st.button("🧹 Limpar conversa", use_container_width=True, key="clear_chat_bottom"):
    st.session_state.hist = [("bot", "Conversa limpa! Quer falar sobre cursos, inscrição, EAD, unidades ou conhecer melhor o Aprendiz? 🙂", "feliz", None)]
    st.session_state.awaiting_location = False
    st.session_state.awaiting_contact = False
    _rerun()

st.markdown("<div style='text-align: center; margin-top: 10px; font-size: 0.8rem; color: #888;'>Aprendiz — conversa natural, foco no Senac e no que importa pra você.</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
