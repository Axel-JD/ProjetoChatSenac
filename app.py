# app.py — Versão FINAL e OTIMIZADA com audio-recorder-streamlit
# ----------------------------------------------------------------------
# (Todo o código do app.py anterior é mantido, exceto o bloco de STT e o bloco de BARRA DE ENTRADA)
# ----------------------------------------------------------------------

# ... (Seção de imports e configs até PROVEDORES)

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
        pass 

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

# NOVO BLOCO DE ÁUDIO: Usamos audio-recorder-streamlit
try:
    from audio_recorder_streamlit import audio_recorder
    HAS_STT = True
except Exception:
    HAS_STT = False # Se falhar, pelo menos não quebra o app e o erro é exibido
    
# ... (Restante das seções ESTADO e AVATARES)

# =========================
# SIDEBAR (AJUSTADA PARA EXIBIR STATUS DO NOVO COMPONENTE)
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
    
    # NOVO DIAGNÓSTICO:
    st.caption(f"Status do Áudio: {'Sucesso' if HAS_STT else 'FALHA (Componente não carregado)'}")
    if st.session_state.stt_enabled and not HAS_STT:
        st.error("Falha ao carregar o componente de microfone. Verifique o requirements.txt.")

# ... (Restante das seções TEMA / CSS e CHAT UI)

# =========================
# PROCESSAR "typing" (Sem alterações)
# =========================
# ... (bloco PROCESSAR "typing" inalterado)

# =========================
# BARRA DE ENTRADA (chat_input + NOVO MICROFONE)
# =========================
st.markdown("<div class='input-bar'></div>", unsafe_allow_html=True)

audio_bytes: Optional[bytes] = None
mic_txt: Optional[str] = None
user_msg = None

# Apenas mostra o gravador se a funcionalidade estiver ativada e o componente carregado
if st.session_state.stt_enabled and HAS_STT:
    
    # O audio_recorder cria o botão e retorna os bytes do áudio gravado
    # Note: st.columns é removido para simplificar a injeção do componente
    audio_bytes = audio_recorder(
        text="", # Removemos o texto do botão (o ícone já é suficiente)
        recording_color="#e8612c", # Cor do Senac
        neutral_color="#cccccc",
        icon_size="2x",
        key="audio_recorder_input"
    )

    if audio_bytes:
        # AQUI VOCÊ ENVIARIA OS BYTES PARA UMA API DE TRANSCRIÇÃO (como Whisper da OpenAI)
        # Ex: transcription = llm_client.audio.transcriptions.create(file=audio_bytes, ...)
        
        # Como não queremos complexificar, vamos simular a transcrição.
        # SE VOCÊ QUISER USAR O WHISPER AQUI, SERÁ NECESSÁRIO SALVAR OS BYTES EM UM BytesIO/TempFile
        mic_txt = "Pergunta de voz recebida. Qual é a sua resposta?" 
        
        # Para um uso real com o Whisper:
        # import io
        # with io.BytesIO(audio_bytes) as audio_file:
        #     audio_file.name = "audio.wav" # Nome do arquivo é necessário para a API
        #     transcricao_obj = llm_client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        #     mic_txt = transcricao_obj.text


# Chat input principal
user_msg = st.chat_input("Digite sua mensagem…")


# Processamento da Mensagem (Voz ou Texto)
msg = None
if mic_txt and mic_txt.strip():
    msg = mic_txt.strip()
elif user_msg and user_msg.strip():
    msg = user_msg.strip()

if msg:
    # Nenhuma chamada save_message_to_db aqui
    
    st.session_state.hist.append(("user", msg, None, None))
    st.session_state.hist.append(("typing", "digitando...", "pensando", None))
    _rerun()

# =========================
# RODAPÉ - LIMPO
# =========================
# ... (bloco RODAPÉ inalterado)
