# app.py — Conecta Senac • Aprendiz (conversa natural + foco no Senac + pesquisas só quando necessário)
# LLM: OpenAI (se houver) → Groq (grátis, se houver).
# Busca: Tavily (se houver) → DDGS (grátis). Sem pesquisas desnecessárias.
# Saída da IA SEMPRE em JSON: {"emotion":"feliz|neutro","content":"..."}; salvamos em /respostas.

import os
import re
import json
import base64
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import streamlit as st
import streamlit.components.v1 as components

# =========================
# CONFIG / ASSETS
# =========================
APP_TITLE = "Conecta Senac — Aprendiz"
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
AVATAR_DIR = os.path.join(os.getcwd(), "emocoes")
OUTBOX_DIR = Path("respostas")

def ensure_dir(p: Path) -> None:
    try:
        p.mkdir(exist_ok=True, parents=True)
    except Exception:
        pass

ensure_dir(OUTBOX_DIR)

FAVICON_ICO = os.path.join(ASSETS_DIR, "favicon.ico")
FAVICON_PNG = os.path.join(ASSETS_DIR, "favicon.png")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo_conecta_senac_transparente.png")

def _first_existing(*paths: str) -> Optional[str]:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None

PAGE_ICON = _first_existing(FAVICON_ICO, FAVICON_PNG) or "🎓"
st.set_page_config(page_title=APP_TITLE, page_icon=PAGE_ICON, layout="centered", initial_sidebar_state="collapsed")

# Compat rerun
_rerun = (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)

def _file_to_b64(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

# =========================
# PROVEDORES (LLM + BUSCA)
# =========================
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

TAVILY_KEY = os.getenv("TAVILY_API_KEY", "").strip()

llm_provider = None
llm_client = None
if API_KEY:
    from openai import OpenAI
    llm_provider = "openai"
    llm_client = OpenAI(api_key=API_KEY)
elif GROQ_KEY:
    from groq import Groq
    llm_provider = "groq"
    llm_client = Groq(api_key=GROQ_KEY)

# DuckDuckGo Search (novo pacote ddgs) ou fallback
try:
    from ddgs import DDGS  # pacote novo (evita warning de renome)
except Exception:
    try:
        from duckduckgo_search import DDGS  # fallback
    except Exception:
        DDGS = None

# ======== STT (voz -> texto) via componente streamlit-mic-recorder ========
try:
    # pip install streamlit-mic-recorder
    from st_mic_recorder import speech_to_text, mic_recorder
    HAS_STT = True
except Exception:
    HAS_STT = False

# =========================
# ESTADO
# =========================
if "hist" not in st.session_state:
    # (quem, texto, emocao, fontes)
    st.session_state.hist: List[Tuple] = [
        ("bot",
         "Olá! Eu sou o **Aprendiz**, do **Conecta Senac**. Posso conversar sobre nossos cursos, inscrições, EAD, unidades — e também explicar como eu funciono. Como posso te ajudar?",
         "feliz",
         None)
    ]
if "awaiting_location" not in st.session_state:
    st.session_state.awaiting_location = False
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False
if "font_size" not in st.session_state:
    st.session_state.font_size = 1.0
if "avatars" not in st.session_state:
    st.session_state.avatars = {}
if "tts_enabled" not in st.session_state:
    st.session_state.tts_enabled = True
if "stt_enabled" not in st.session_state:
    st.session_state.stt_enabled = True  # acessibilidade ativada por padrão

# =========================
# AVATARES
# =========================
@st.cache_data(show_spinner=False)
def carregar_avatars(avatar_dir: str) -> dict:
    nomes = ["feliz", "neutro", "pensando"]
    return {n: _file_to_b64(os.path.join(avatar_dir, f"{n}.png")) for n in nomes}

st.session_state.avatars = st.session_state.avatars or carregar_avatars(AVATAR_DIR)

def avatar_img(emocao: str) -> str:
    b64img = st.session_state.avatars.get(emocao)
    return f"<img class='avatar-img' src='data:image/png;base64,{b64img}' alt='{emocao}'/>" if b64img else "<div class='avatar-emoji'>🎓</div>"

# =========================
# SIDEBAR
# =========================
with st.sidebar:
    st.header("⚙️ Preferências")
    st.session_state.dark_mode = st.toggle("🌙 Modo escuro", value=st.session_state.dark_mode)
    st.session_state.tts_enabled = st.toggle("🔊 Leitura em voz alta", value=st.session_state.tts_enabled, help="O Aprendiz lerá as respostas em voz alta.")
    st.session_state.stt_enabled = st.toggle("🎤 Entrada por voz (microfone)", value=st.session_state.stt_enabled, help="Ditado por voz no navegador.")
    st.session_state.font_size = st.slider("♿ Tamanho da fonte", 1.0, 1.5, st.session_state.font_size, 0.05, help="Aumenta o tamanho da fonte da conversa.")
    temp = st.slider("Criatividade (temperature)", 0.0, 1.0, 0.35, 0.05)
    web_toggle = st.toggle("🔎 Ativar pesquisa web (somente quando fizer sentido)", value=True)
    st.caption(f"LLM: {'OpenAI' if llm_provider=='openai' else ('Groq (grátis)' if llm_provider=='groq' else '⚠️ não configurado')}")
    st.caption(f"Busca: {'Tavily' if TAVILY_KEY else 'DDGS (grátis) com viés Senac'}")
    if st.session_state.stt_enabled and not HAS_STT:
        st.info("Para usar o microfone: `pip install streamlit-mic-recorder` e reinicie o app.")

# =========================
# TEMA / CSS
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

LOGO_B64 = _file_to_b64(LOGO_PATH) if os.path.exists(LOGO_PATH) else None
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
body {{ background: linear-gradient(180deg, var(--bg1) 0%, var(--bg2) 100%) fixed; }}
.wrap {{ width:100%; max-width:900px; margin:0 auto; }}
.header {{ background: linear-gradient(135deg, var(--h1) 0%, var(--h2) 100%); color:#fff; padding:12px 14px; border-radius:16px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.brand {{ display:flex; align-items:center; gap:12px; }}
.brand img {{ height:38px; object-fit:contain; }}
.brand h2 {{ margin:0; font-weight:700; letter-spacing:.2px; }}
.tag {{ font-size:12px; background:rgba(255,255,255,.18); padding:4px 10px; border-radius:999px; border:1px solid rgba(255,255,255,.25) }}
.chat-box {{ background:var(--fundo); border:2px solid var(--borda); border-radius:16px; padding:12px; max-height:72vh; overflow-y:auto; box-shadow:0 10px 24px rgba(25,76,145,.08); margin-top:12px; }}
.msg {{ display:inline-block; white-space:pre-wrap; overflow-wrap:anywhere; padding:12px 14px; border-radius:16px; margin:6px 0; max-width:78%; line-height:1.28; font-size:{dynamic_font_size}rem; }}
.msg-user {{ background:var(--user); color:var(--userTxt); margin-left:auto; border-bottom-right-radius:8px; box-shadow:0 6px 16px rgba(14,78,155,.18); }}
.msg-bot {{ background:var(--bot); color:var(--botTxt); margin-right:auto; border-bottom-left-radius:8px; box-shadow:0 6px 16px rgba(244,121,32,.18); }}
.bubble-row {{ display:flex; align-items:flex-end; gap:10px; }}
.avatar-shell {{ flex:0 0 auto; display:flex; align-items:flex-end; }}
.avatar-img {{ width:56px; height:56px; border-radius:50%; object-fit:cover; box-shadow:0 4px 12px rgba(138,67,0,.16); }}
.avatar-emoji {{ width:56px; height:56px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#ffd9bf; color:#8a4300; font-size:28px; }}
.avatar-user {{ width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#cfe3ff; color:#0c3d88; font-size:18px; }}
.typing-bubble {{ background:var(--bot); color:var(--botTxt); margin-right:auto; border-radius:16px; border-bottom-left-radius:8px; padding:10px 14px; display:inline-flex; align-items:center; gap:6px; }}
.dot {{ width:6px; height:6px; border-radius:50%; background:#fff; opacity:.75; animation: blink 1.4s infinite ease-in-out both; }}
.dot:nth-child(2) {{ animation-delay:.2s; }} .dot:nth-child(3) {{ animation-delay:.4s; }}
@keyframes blink {{ 0%, 80%, 100% {{ transform: scale(0); opacity: .3; }} 40% {{ transform: scale(1); opacity: 1; }} }}
a {{ color:var(--link); text-decoration:none; }} a:hover {{ text-decoration:underline; }}
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='wrap'>", unsafe_allow_html=True)
if LOGO_B64:
    st.markdown(f"<div class='header'><div class='brand'><img src='data:image/png;base64,{LOGO_B64}' alt='Conecta Senac • Aprendiz'/><h2>Conecta Senac • Aprendiz</h2></div><span class='tag'>conversa natural • foco Senac</span></div>", unsafe_allow_html=True)
else:
    st.markdown("<div class='header'><div class='brand'><span>🎓</span><h2>Conecta Senac • Aprendiz</h2></div><span class='tag'>conversa natural • foco Senac</span></div>", unsafe_allow_html=True)

# =========================
# SUGESTÕES (todas on-topic)
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
        st.session_state.hist.append(("user", texto, None, None))
        st.session_state.hist.append(("typing", "digitando...", "pensando", None))
        _rerun()

# =========================
# ESCOPO / CLASSIFICAÇÃO SUAVE
# =========================
SENAC_TERMS = [
    "senac","senac rs","senacrs","senac.br","senacrs.com.br",
    "curso","cursos","matrícula","matricula","inscrição","inscricao",
    "unidade","unidades","ead","ensino a distância","ensino a distancia",
    "mensalidade","bolsa","área","tecnologia","gastronomia","gestão","idiomas",
    "horário","horario","endereço","endereco","pagamento","certificado","grade curricular","carga horária","carga horaria",
    "conecta senac","aprendiz"
]
SMALLTALK_TERMS = [
    "aprendiz","conecta senac","assistente","chatbot",
    "ia","i.a.","inteligência artificial","inteligencia artificial",
    "sobre você","sobre voce","quem é você","quem é voce","quem é vc","o que você faz","como você funciona","como voce funciona",
    "privacidade","dados","limitações","limitacoes","regras","politica","projeto"
]
AMBIGUOUS_TERMS = [
    "carreira","emprego","trabalho","currículo","curriculo","estágio","estagio",
    "faculdade","universidade","enem","vestibular","curso online","curso técnico","curso tecnico",
    "área de ti","área de tecnologia","mercado de trabalho","programação","design","administração","gastronomia"
]

def classify_scope_heuristic(text: str) -> str:
    t = (text or "").lower()
    if any(term in t for term in SENAC_TERMS): return "on"
    if any(term in t for term in SMALLTALK_TERMS): return "on"   # small talk permitido
    if any(term in t for term in AMBIGUOUS_TERMS): return "ambiguous"
    return "off"

def classify_scope_ai(text: str) -> Optional[str]:
    if llm_client is None:
        return None
    instr = (
        "Classifique o escopo da mensagem. Responda SOMENTE JSON:\n"
        '{ "scope": "senac" | "maybe" | "other" }\n'
        "- 'senac': Senac, seus cursos/serviços, OU small talk sobre o assistente/IA/projeto Conecta Senac.\n"
        "- 'maybe': educação/carreira genérica que pode ser conectada ao Senac.\n"
        "- 'other': tema claramente alheio.\n"
        "Não explique."
    )
    msgs = [{"role":"system","content": instr}, {"role":"user","content": text.strip()}]
    try:
        if llm_provider == "openai":
            r = llm_client.chat.completions.create(model=OPENAI_MODEL, messages=msgs, temperature=0.0, max_tokens=10)
            raw = (r.choices[0].message.content or "").strip()
        else:
            r = llm_client.chat.completions.create(model=GROQ_MODEL, messages=msgs, temperature=0.0, max_tokens=10)
            raw = (r.choices[0].message.content or "").strip()
        scope = json.loads(raw).get("scope","").lower().strip()
        # normalize para on/ambiguous/off
        if scope == "senac": return "on"
        if scope == "maybe": return "ambiguous"
        if scope == "other": return "off"
        return None
    except Exception:
        return None

def soft_scope_gate(text: str) -> str:
    ai = classify_scope_ai(text)
    if ai in {"on","ambiguous","off"}:
        return ai
    # fallback heurístico
    return classify_scope_heuristic(text)

# =========================
# BUSCA — só quando fizer sentido (e com viés Senac)
# =========================
EXPLICIT_SEARCH_TOKENS = ["pesquise", "pesquisa", "procurar", "procure", "buscar", "busque"]
ADDR_TOKENS = ["onde fica","endereço","endereco","unidade","unidades","localização","localizacao","perto de mim"]
INFO_TOKENS = ["horário","horario","telefone","preço","valor","mensalidade","data","quando","link","site","matrícula","inscrição","inscricao","grade curricular","carga horária","carga horaria"]

def should_search_web(text: str) -> bool:
    t = (text or "").lower()
    # 1) se o usuário pedir explicitamente
    if any(tok in t for tok in EXPLICIT_SEARCH_TOKENS): return True
    # 2) endereços ou infos específicas + contexto do Senac
    if any(tok in t for tok in ADDR_TOKENS + INFO_TOKENS):
        if "senac" in t or any(tok in t for tok in ["curso","unidade","matrícula","inscrição","inscricao","ead"]):
            return True
    return False

def web_search(query: str, max_results: int = 6):
    # Tavily
    if TAVILY_KEY:
        try:
            from tavily import TavilyClient
            tv = TavilyClient(api_key=TAVILY_KEY)
            # Viés para domínios do Senac
            q = query if "senac" in query.lower() else f"site:senacrs.com.br OR site:senac.br {query}"
            res = tv.search(query=q, max_results=max_results, search_depth="basic")
            if isinstance(res, dict) and res.get("results"):
                return [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content")} for r in res["results"]]
        except Exception:
            pass
    # DDGS (grátis)
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
# PROMPTS / GERAÇÃO (sempre JSON)
# =========================
BASE_SISTEMA = (
    "Você é o Aprendiz, assistente do projeto Conecta Senac. Converse de forma natural, gentil e útil (PT-BR). "
    "Foque em Senac (especialmente Senac RS), seus cursos/serviços, inscrições, EAD/presencial, valores/bolsas, unidades/endereços/horários, eventos e no próprio Aprendiz/Conecta Senac (small talk permitido). "
    "Evite pesquisas desnecessárias. Só use dados da web quando receber do sistema um contexto com links/trechos; caso contrário, evite inventar números/endereços. "
    "Se o tema for claramente alheio, use UMA frase acolhedora convidando a voltar ao Senac (sem soar restritivo). "
    "Para endereços/unidades, NUNCA adivinhe: peça a cidade se faltar; se houver fontes, cite links. "
    "Formate ESTRITAMENTE como JSON válido (sem texto fora do JSON): "
    '{"emotion":"feliz|neutro","content":"<markdown conciso>"}'
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
    for who, msg, *_ in st.session_state.hist[-(limit_pairs*2):]:
        msgs.append({"role":"user" if who=="user" else "assistant", "content": msg})
    return msgs

def llm_json(messages: List[Dict[str,str]], temperature=0.35, max_tokens=500) -> dict:
    if llm_client is None:
        return {"emotion":"neutro","content":"⚠️ Para respostas completas, configure GROQ_API_KEY (grátis) ou OPENAI_API_KEY."}
    full = [{"role":"system","content": BASE_SISTEMA}] + messages
    try:
        if llm_provider == "openai":
            r = llm_client.chat.completions.create(model=OPENAI_MODEL, messages=full, temperature=temperature, max_tokens=max_tokens)
            raw = (r.choices[0].message.content or "").strip()
        else:
            r = llm_client.chat.completions.create(model=GROQ_MODEL, messages=full, temperature=temperature, max_tokens=max_tokens)
            raw = (r.choices[0].message.content or "").strip()
    except Exception as e:
        return {"emotion":"neutro","content":f"⚠️ Problema técnico para gerar a resposta: {e}"}
    # Parse seguro
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"emotion":"feliz","content":raw}

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
    # de-dup
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

    # Escopo suave
    scope = soft_scope_gate(p)  # on | ambiguous | off
    if scope == "off":
        return {"emotion":"feliz","content":"Vamos focar no **Senac** para te ajudar melhor — cursos, inscrições, EAD e unidades. Qual desses temas você quer explorar agora? 🙂"}, []

    # Pedir cidade quando for sobre endereço/unidade
    if any(tok in pl for tok in ["onde fica","endereço","endereco","unidade","unidades","localização","localizacao","perto de mim"]):
        city = extract_city(p)
        if not city:
            st.session_state.awaiting_location = True
            return {"emotion":"feliz","content":"Para localizar certinho, me diz a **cidade** (e o estado, se for fora do RS). 😉"}, []

    # Se aguardando cidade e a mensagem parece ser a cidade
    if st.session_state.awaiting_location and not any(k in pl for k in ["senac","curso","inscri","pagamento","unidade","matrícula","ead"]):
        st.session_state.awaiting_location = False
        city = p.title()
        if web_toggle:
            fontes = responder_endereco(city)
        msgs = _last_msgs()
        if fontes:
            ctx = "\n".join([f"[{i+1}] {h['title']} — {h['url']}\n{(h.get('content') or '')[:600]}" for i,h in enumerate(fontes)])
            msgs.insert(0, {"role":"system","content":"Contexto de pesquisa:\n"+ctx})
        msgs.append({"role":"user","content": f"O usuário informou a cidade: {city}. Oriente sem inventar e cite links confiáveis se possível."})
        payload = llm_json(msgs, temperature=temperature)
        return payload, fontes

    # Decidir se precisa buscar (somente quando fizer sentido)
    if web_toggle and should_search_web(p):
        fontes = web_search(p, 6)

    msgs = _last_msgs()
    if scope == "ambiguous":
        msgs.insert(0, {"role":"system","content":"A pergunta é geral; conecte naturalmente ao contexto do Senac/Conecta Senac/Aprendiz sem soar restritivo."})
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
        st.markdown(
            "<div class='bubble-row' style='justify-content:flex-start;'>"
            f"<div class='avatar-shell'>{avatar_img(emo or 'feliz')}</div>"
            f"<div class='msg msg-bot'>{msg}</div>"
            "</div>",
            unsafe_allow_html=True
        )
        if fontes:
            links = "".join([f"<li><a href='{f.get('url','')}' target='_blank'>{f.get('title','Fonte')}</a></li>" for f in fontes if f.get('url')])
            if links:
                st.markdown(f"<ul class='link-list' style='margin:6px 0 10px 50px'>{links}</ul>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Auto-scroll
components.html("<script>const box=parent.document.querySelector('#chat'); if(box){box.scrollTop=box.scrollHeight;}</script>", height=0)

# =========================
# EMOÇÕES (feliz por padrão; neutro somente erro real)
# =========================
ERROR_MARKERS = ["⚠️","erro","error","não consegui","nao consegui","não foi possível","nao foi possivel","problema técnico","problema tecnico","invalid api key","rate limit","timeout","falha","indisponível","indisponivel"]

def decide_emotion(content: str) -> str:
    txt = (content or "").lower()
    if not txt: return "neutro"
    if any(m in txt for m in ERROR_MARKERS): return "neutro"
    return "feliz"

# =========================
# TTS (texto → fala) — opcional
# =========================
def text_to_speech_component(text: str):
    # simplifica markdown para fala
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
    payload, fontes = gerar_resposta_json(pergunta, temp)
    content = (payload.get("content") or "").strip()
    final_emotion = decide_emotion(content)
    _save_json({"emotion": final_emotion, "content": content}, fontes)
    st.session_state.hist[-1] = ("bot", content or "Posso te ajudar com algo do Senac? 🙂", final_emotion, fontes)

    # TTS se habilitado
    if st.session_state.tts_enabled and content:
        text_to_speech_component(content)

    _rerun()

# =========================
# BARRA DE ENTRADA (texto + microfone + enviar) — CORRIGIDO
# =========================
# Observação: este bloco substitui o st.chat_input e qualquer bloco de voz separado.

st.markdown("""
<style>
.input-bar {margin-top:10px; background:transparent;}
.fake-mic {
  display:flex; align-items:center; justify-content:center;
  height:38px; border:1px dashed #bbb; border-radius:8px; color:#888;
  font-size:14px;
}
</style>
""", unsafe_allow_html=True)

with st.container():
    st.markdown("<div class='input-bar'></div>", unsafe_allow_html=True)

    # Linha com 2 colunas: [MIC]  |  [FORM (texto + enviar)]
    c_mic, c_form = st.columns([0.14, 0.86])

    # 1) Microfone (fora do form, para evitar erro de botão dentro de st.form)
    mic_txt = None
    with c_mic:
        if st.session_state.get("stt_enabled", True) and 'HAS_STT' in globals() and HAS_STT:
            # Componente do mic (gera texto ao finalizar a fala)
            mic_txt = speech_to_text(
                language='pt-BR',
                start_prompt="🎤 Falar",
                stop_prompt="⏹️ Parar",
                just_once=True,
                use_container_width=True,
                key="stt_inline"
            )
        else:
            # Apenas um marcador visual (NÃO é botão real) — fora de st.form
            st.markdown("<div class='fake-mic'>🎤 microfone off</div>", unsafe_allow_html=True)
            if st.session_state.get("stt_enabled", True):
                st.caption("Ative o microfone na barra lateral ou instale `streamlit-mic-recorder`.")

    # 2) Formulário (somente texto + submit)
    with c_form:
        with st.form("chat_send", clear_on_submit=True):
            c_input, c_send = st.columns([0.78, 0.22])
            with c_input:
                typed = st.text_input("Digite sua mensagem…", key="typed_text", label_visibility="collapsed")
            with c_send:
                sent = st.form_submit_button("Enviar", use_container_width=True)

    # Prioridade de envio:
    #  - Se veio texto do microfone, envia direto (não depende do Submit)
    #  - Senão, envia se clicou em "Enviar" com texto digitado
    msg = None
    if mic_txt and isinstance(mic_txt, str) and mic_txt.strip():
        msg = mic_txt.strip()
    elif sent and typed and typed.strip():
        msg = typed.strip()

    if msg:
        st.session_state.hist.append(("user", msg, None, None))
        st.session_state.hist.append(("typing", "digitando...", "pensando", None))
        _rerun()

# =========================
# RODAPÉ
# =========================
c1, c2 = st.columns(2)
with c1:
    if st.button("🧹 Limpar conversa", use_container_width=True):
        st.session_state.hist = [("bot", "Conversa limpa! Quer falar sobre cursos, inscrição, EAD, unidades ou conhecer melhor o Aprendiz? 🙂", "feliz", None)]
        st.session_state.awaiting_location = False
        _rerun()
with c2:
    st.caption("Aprendiz — conversa natural, foco no Senac e no que importa pra você.")
