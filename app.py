# app.py — Conecta Senac • Aprendiz
# Versão Final (SQLite, Foco Senac, UI Limpa, Modo Escuro e STT integrados)
# ----------------------------------------------------------------------
# Dependências: Streamlit, openai, tavily-python, ddgs, streamlit-mic-recorder
# Persistência: Histórico e Contatos salvos em conecta_senac.db (SQLite).
# Foco: LLM é forçado a conectar perguntas off-topic ao Senac.
# UI: Botão de microfone integrado.# =========================
# DIAGNÓSTICO TEMPORÁRIO
# =========================
if not HAS_STT:
    st.error("Diagnóstico: HAS_STT é FALSO. A importação da biblioteca falhou, mesmo se instalada.")
# ----------------------------------------------------------------------

import os
import re
import json
import base64
import unicodedata
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import streamlit as st
import streamlit.components.v1 as components

# =========================
# CONFIG / ASSETS / DB (SQLITE)
# =========================
APP_TITLE = "Conecta Senac — Aprendiz"
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = ASSETS_DIR
OUTBOX_DIR = Path("respostas")
DB_FILE = "conecta_senac.db" # Arquivo do banco de dados SQLite

def ensure_dir(p: Path) -> None:
    try:
        p.mkdir(exist_ok=True, parents=True)
    except Exception:
        pass

ensure_dir(OUTBOX_DIR)

# --- Funções de Banco de Dados SQLite ---
def init_db(db_path: str) -> None:
    """Cria as tabelas de histórico e contatos se não existirem."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Tabela 1: Histórico de Conversa
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                speaker TEXT NOT NULL,
                message TEXT NOT NULL,
                emotion TEXT,
                sources_json TEXT
            )
        """)
        
        # Tabela 2: Contatos Capturados (Leads)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_time TEXT NOT NULL,
                name TEXT,
                email TEXT UNIQUE NOT NULL,
                raw_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao inicializar o banco de dados: {e}")

def save_message_to_db(db_path: str, who: str, msg: str, emo: Optional[str] = None, fontes: Optional[list] = None) -> None:
    """Salva uma mensagem individual no histórico."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        sources_str = json.dumps(fontes or [])

        cursor.execute(
            "INSERT INTO history (timestamp, speaker, message, emotion, sources_json) VALUES (?, ?, ?, ?, ?)",
            (timestamp, who, msg, emo, sources_str)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar mensagem no DB: {e}")

def save_contact_to_db(db_path: str, name: str, email: str, raw_message: str) -> bool:
    """Salva um novo contato no banco de dados. Retorna True se salvo, False se já existe."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        capture_time = datetime.now().isoformat()
        
        cursor.execute(
            "INSERT INTO contacts (capture_time, name, email, raw_message) VALUES (?, ?, ?, ?)",
            (capture_time, name, email.lower(), raw_message)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Se o e-mail já existir
        return False 
    except Exception as e:
        print(f"Erro ao salvar contato no DB: {e}")
        return False

# Inicializa o banco de dados ao iniciar o app
init_db(DB_FILE)
# --- Fim Funções de Banco de Dados ---

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
# PROVEDORES (LLM + BUSCA)
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
        st.sidebar.error("Pacote 'openai' ausente/incompatível ou chave inválida.")
        st.sidebar.caption(f"Detalhe técnico: {e!r}")

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

try:
    from st_mic_recorder import speech_to_text
    HAS_STT = True
except Exception:
    HAS_STT = False

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
    # ÚNICA INFORMAÇÃO DE INSTALAÇÃO DO MICROFONE FICA AQUI
    if st.session_state.stt_enabled and not HAS_STT:
        st.info("Para microfone no Cloud: adicione 'streamlit-mic-recorder' ao requirements.txt.")

# =========================
# TEMA / CSS (FUNDO CORRIGIDO)
# =========================
DARK = st.session_state.dark_mode
if DARK:
    COR_BG1, COR_BG2 = "#0b1220", "#0f172a"
    COR_FUNDO = "#0f172a"; COR_BORDA = "#1e3a8a"
    COR_USER = "#1e40af"; COR_USER_TXT = "#e5e7eb"
    COR_BOT = "#F47920"; COR_BOT_TXT = "#111827"
    COR_LINK = "#93c5fd"; HEADER_GRAD_1, HEADER_GRAD_2 = "#0e4e9b", "#2567c4"
else:
    COR_BG1, COR_BG2 = "#fbfdff", "#eef3fb"
    COR_FUNDO = "#F7F9FC"; COR_BORDA = "#0E4E9B"
    COR_USER = "#0E4E9B"; COR_USER_TXT = "#FFFFFF"
    COR_BOT = "#F47920"; COR_BOT_TXT = "#FFFFFF"
    COR_LINK = "#0A66C2"; HEADER_GRAD_1, HEADER_GRAD_2 = "#0e4e9b", "#2567c4"

BASE_FONT_SIZE_REM = 0.985
dynamic_font_size = BASE_FONT_SIZE_REM * st.session_state.font_size

st.markdown(f"""
<style>
:root {{
  --bg1:{COR_BG1}; --bg2:{COR_BG2}; --fundo:{COR_FUNDO}; --borda:{COR_BORDA};
  --user:{COR_USER}; --userTxt:{COR_USER_TXT}; --bot:{COR_BOT}; --botTxt:{COR_BOT_TXT};
  --link:{COR_LINK}; --h1:{HEADER_GRAD_1}; --h2:{HEADER_GRAD_2};
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
.input-bar {{ margin-top:10px; }}
.fake-mic {{ display:flex; align-items:center; justify-content:center; height:38px; border:1px dashed #bbb; border-radius:8px; color:#888; font-size:14px; }}
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
    if cols[i].button(texto, use_container_width=True):
        save_message_to_db(DB_FILE, "user", texto)
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
# BUSCA WEB (Tavily → DDGS)
# =========================
EXPLICIT_SEARCH_TOKENS = ["pesquise", "pesquisa", "procurar", "procure", "buscar", "busque"]
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

def web_search(query: str, max_results: int = 6):
    if TAVILY_KEY:
        try:
            from tavily import TavilyClient
            tv = TavilyClient(api_key=TAVILY_KEY)
            q = query if "senac" in query.lower() else f"site:senacrs.com.br OR site:senac.br {query}"
            res = tv.search(query=q, max_results=max_results, search_depth="basic")
            if isinstance(res, dict) and res.get("results"):
                return [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content")} for r in res["results"]]
        except Exception:
            pass
    if DDGS is None: return []
    try:
        hits = []
        q = query if "senac" in query.lower() else f"site:senacrs.com.br {query}"
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=max_results):
                hits.append({"title": r.get("title"), "url": r.get("href") or r.get("url"), "content": r.get("body")})
        return hits
    except Exception:
        return []

# =========================
# PROMPTS / LLM (sempre JSON)
# =========================
BASE_SISTEMA = (
    "Você é o Aprendiz, assistente do projeto Conecta Senac. Converse de forma natural, gentil e útil (PT-BR). "
    "Seu foco ABSOLUTO é no Senac (especialmente Senac RS), seus cursos/serviços, inscrições, EAD/presencial, unidades/endereços/horários, eventos e no próprio Aprendiz/Conecta Senac (small talk permitido). "
    "NÃO responda perguntas que não tenham ligação com o Senac. Se a pergunta for alheia, você DEVE **redirecionar** ou **conectar** o assunto ao Senac na sua resposta. (Ex: 'Você me perguntou sobre [Assunto Geral], mas o Senac tem [Curso Relacionado].') "
    "Se o usuário demonstrar interesse (ex: 'Quero me inscrever', 'Me diga o próximo passo', 'Gostei e quero mais'), a próxima resposta DEVE ser uma pergunta para ele, verificando se você pode pegar o NOME e E-MAIL dele e armazenar para que o Senac entre em contato. "
    "Evite pesquisas desnecessárias. Só use dados da web quando receber do sistema um contexto com links/trechos. "
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
            
            if save_contact_to_db(DB_FILE, name, email, p):
                return {"emotion": "feliz", "content": f"Perfeito, **{name}**! O e-mail **{email}** foi salvo e a equipe Senac entrará em contato em breve. Enquanto isso, mais alguma dúvida sobre nossos cursos?"}, []
            else:
                return {"emotion": "neutro", "content": f"O e-mail **{email}** já está registrado. A equipe Senac entrará em contato. Qual curso te interessa agora?"}, []
        else:
            return {"emotion": "duvida", "content": "Não consegui identificar seu e-mail. Por favor, digite seu **NOME** e **E-MAIL** para contato, ou diga 'Não' se não quiser prosseguir."}, []
    
    # --- BLOCO 2: INÍCIO DA CAPTURA (GATILHO) ---
    if any(k in pl for k in ["quero me inscrever", "proximo passo", "como me inscrevo", "gostei e quero mais", "quero começar"]):
        st.session_state.awaiting_contact = True
        return {"emotion": "feliz", "content": "Excelente! Posso te ajudar com o processo. Para agilizar seu atendimento com um consultor do Senac, você me autoriza a registrar seu nome e e-mail no nosso banco de dados?"}, []

    # --- BLOCO 3: LOCALIZAÇÃO DE UNIDADE (SE NECESSÁRIO) ---
    if any(tok in pl for tok in ["onde fica","endereço","endereco","unidade","unidades","localização","localizacao","perto de mim"]):
        city = extract_city(p)
        if not city:
            st.session_state.awaiting_location = True
            return {"emotion":"feliz","content":"Para localizar certinho, me diz a **cidade** (e o estado, se for fora do RS). 😉"}, []

    if st.session_state.awaiting_location and not any(k in pl for k in ["senac","curso","inscri","pagamento","unidade","matrícula","ead"]):
        st.session_state.awaiting_location = False
        city = p.title()
        if web_toggle:
            fontes = responder_endereco(city)
        
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
    if web_toggle and should_search_web(p):
        fontes = web_search(p, 6)

    if fontes:
        ctx = "\n".join([f"[{i+1}] {h['title']} — {h['url']}\n{(h.get('content') or '')[:600]}" for i,h in enumerate(fontes)])
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
        if fontes:
            links = "".join([f"<li><a href='{f.get('url','')}' target='_blank'>{f.get('title','Fonte')}</a></li>" for f in fontes if f.get('url')])
            if links:
                st.markdown(f"<ul class='link-list' style='margin:6px 0 10px 50px'>{links}</ul>", unsafe_allow_html=True)

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
# PROCESSAR "typing" (SALVA NO DB)
# =========================
if st.session_state.hist and st.session_state.hist[-1][0] == "typing":
    pergunta = ""
    for who, msg, *_ in reversed(st.session_state.hist[:-1]):
        if who == "user":
            pergunta = msg
            break
            
    payload, fontes = gerar_resposta_json(pergunta, st.session_state.get("temperature", 0.35))
    
    final_content = (payload.get("content") or "Desculpe, não consegui processar a resposta.").strip()
    emotion = payload.get("emotion", "feliz")

    valid_emotions = ["feliz", "neutro", "pensando", "triste", "duvida"]
    final_emotion = emotion if emotion in valid_emotions else "feliz"

    # Salva a mensagem do BOT no DB
    save_message_to_db(DB_FILE, "bot", final_content, final_emotion, fontes)
    
    try:
        _ = _save_json({"emotion": final_emotion, "content": final_content}, fontes)
    except Exception:
        pass
        
    st.session_state.hist[-1] = ("bot", final_content or "Posso te ajudar com algo do Senac? 🙂", final_emotion, fontes)
    
    if st.session_state.tts_enabled and final_content:
        text_to_speech_component(final_content)
    
    _rerun()

# =========================
# BARRA DE ENTRADA (chat_input + MICROFONE) - UI LIMPA
# =========================
st.markdown("<div class='input-bar'></div>", unsafe_allow_html=True)

mic_txt: Optional[str] = None
c_mic, c_hint = st.columns([0.18, 0.82])

with c_mic:
    # Apenas exibe o botão se STT estiver ativado E o pacote instalado
    if st.session_state.stt_enabled and HAS_STT:
        mic_txt = speech_to_text(
            language="pt-BR",
            start_prompt="🎤 Falar",
            stop_prompt="⏹️ Parar",
            just_once=True,
            use_container_width=True,
            key="stt_inline_top",
        )
    # Nenhuma mensagem de "microfone off" ou instalação é exibida aqui.

with c_hint:
    # Removemos qualquer dica para limpar o espaço.
    pass 

user_msg = st.chat_input("Digite sua mensagem…")

msg = None
if isinstance(mic_txt, str) and mic_txt.strip():
    msg = mic_txt.strip()
elif user_msg and user_msg.strip():
    msg = user_msg.strip()

if msg:
    # Salva a mensagem do usuário no DB
    save_message_to_db(DB_FILE, "user", msg) 
    
    st.session_state.hist.append(("user", msg, None, None))
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

