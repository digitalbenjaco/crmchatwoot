"""
Spike da Fase 0 — identidade do agente via cookie, sem JavaScript.

Descoberta que motivou esta versão: o Chatwoot grava as credenciais do agente no
cookie `cw_d_session_info`, com path=/ e sem HttpOnly. Como o CRM roda na MESMA
ORIGEM (atrás do mesmo domínio, em /crm), o navegador envia esse cookie sozinho
em toda requisição. Não é preciso ler storage no cliente nem fazer handoff: o
servidor recebe a credencial e a valida contra o próprio Chatwoot.

Isso é uma asserção verificável — diferente do postMessage do Dashboard App, que
o navegador pode forjar. Resolve de uma vez a autenticação (quem pode ver o board)
e a atribuição (quem moveu o card), que no repositório original dependiam de
Cloudflare Access.

Rodar:
    pip install fastapi uvicorn httpx
    CHATWOOT_BASE_URL=http://chatwoot:3000 uvicorn crm_spike:app --host 0.0.0.0 --port 8000
"""

import json
import os
import urllib.parse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

CHATWOOT_BASE_URL = os.environ["CHATWOOT_BASE_URL"].rstrip("/")
SESSION_COOKIE = "cw_d_session_info"

app = FastAPI(root_path="/crm")


def credencial_do_cookie(request: Request) -> str:
    """Extrai o header Authorization pronto de dentro do cookie de sessao.

    O cookie e um JSON URL-encoded; o campo `authorization` ja vem no formato
    "Bearer <base64>" que o Chatwoot aceita. Repassamos como veio, sem tentar
    remontar a trinca access-token/client/uid na mao.
    """
    bruto = request.cookies.get(SESSION_COOKIE)
    if not bruto:
        raise HTTPException(status_code=401, detail="sessao do Chatwoot ausente")

    try:
        dados = json.loads(urllib.parse.unquote(bruto))
    except ValueError:
        raise HTTPException(status_code=401, detail="cookie de sessao ilegivel")

    autorizacao = dados.get("authorization")
    if not autorizacao:
        raise HTTPException(status_code=401, detail="cookie sem credencial")

    return autorizacao


async def agente_atual(autorizacao: str = Depends(credencial_do_cookie)) -> dict:
    """Pergunta ao Chatwoot de quem e a credencial.

    Resposta 200 prova tres coisas ao mesmo tempo: a credencial e valida, o
    usuario e agente legitimo da instancia, e sabemos exatamente quem e.
    """
    async with httpx.AsyncClient(base_url=CHATWOOT_BASE_URL, timeout=10) as client:
        resposta = await client.get(
            "/api/v1/profile", headers={"authorization": autorizacao}
        )

    if resposta.status_code != 200:
        raise HTTPException(status_code=401, detail="credencial recusada pelo Chatwoot")

    perfil = resposta.json()
    return {
        "id": perfil.get("id"),
        "nome": perfil.get("name"),
        "email": perfil.get("email"),
        "papel": perfil.get("role"),
        "contas": [c.get("id") for c in perfil.get("accounts", [])],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/whoami")
async def whoami(agente: dict = Depends(agente_atual)):
    return agente


@app.get("/", response_class=HTMLResponse)
async def index(agente: dict = Depends(agente_atual)):
    """Pagina do spike. Se ela renderiza com o nome certo, a Fase 0 passou."""
    return f"""
<!doctype html>
<meta charset="utf-8">
<title>CRM</title>
<style>
  body {{ font: 15px/1.6 system-ui, sans-serif; margin: 3rem auto; max-width: 32rem; }}
  a {{ color: inherit; }}
  dt {{ color: #71717a; font-size: 13px; margin-top: .75rem; }}
  dd {{ margin: 0; }}
</style>

<p><a href="/app/accounts/{agente['contas'][0] if agente['contas'] else 1}/conversations">&larr; Conversas</a></p>
<h1>Identidade confirmada</h1>
<p>O servidor validou a credencial contra o Chatwoot. Nenhum JavaScript envolvido.</p>
<dl>
  <dt>Agente</dt><dd>{agente['nome']}</dd>
  <dt>E-mail</dt><dd>{agente['email']}</dd>
  <dt>Papel</dt><dd>{agente['papel']}</dd>
  <dt>Contas</dt><dd>{agente['contas']}</dd>
</dl>
"""


# ---------------------------------------------------------------------------
# Script de navegação injetado no Chatwoot
#
# O nginx na frente do Chatwoot insere <script src="/crm/nav.js"> antes do
# </body> de cada página. Servir o script daqui, e não do proxy, significa que
# ajustar o menu é um redeploy do CRM — o proxy nunca mais precisa mudar.
# ---------------------------------------------------------------------------

NAV_JS = r"""(function () { 'use strict'; var CONFIG = { path: '/crm/', label: 'CRM', itemId: 'crm-nav-item', moldeName: 'Calls', depoisDeName: 'Contacts', }; var ICONE_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" ' + 'stroke="currentColor" stroke-width="2" stroke-linejoin="round" ' + 'aria-hidden="true">' + '<rect x="3" y="4" width="5" height="16" rx="1"></rect>' + '<rect x="9.5" y="4" width="5" height="11" rx="1"></rect>' + '<rect x="16" y="4" width="5" height="7" rx="1"></rect>' + '</svg>'; function cabecalho(name) { return document.querySelector('[role="button"][name="' + name + '"]'); } function trocarTexto(no, texto) { var walker = document.createTreeWalker(no, NodeFilter.SHOW_TEXT, null); var primeiro = true, atual; while ((atual = walker.nextNode())) { if (!atual.nodeValue || !atual.nodeValue.trim()) continue; atual.nodeValue = primeiro ? texto : ''; primeiro = false; } } function trocarIcone(no) { var span = no.querySelector('span[class*="i-lucide-"]'); if (!span) return; span.className = span.className .split(/\s+/) .filter(function (c) { return c.indexOf('i-lucide-') !== 0; }) .join(' '); span.style.display = 'inline-flex'; span.innerHTML = ICONE_SVG; } function limparEstadoAtivo(raiz) { var ativos = raiz.querySelectorAll('[class*="router-link"]'); for (var i = 0; i < ativos.length; i++) { ativos[i].className = ativos[i].className .split(/\s+/) .filter(function (c) { return c.indexOf('router-link') !== 0; }) .join(' '); } } function instalar() { if (document.getElementById(CONFIG.itemId)) return; var molde = cabecalho(CONFIG.moldeName); var referencia = cabecalho(CONFIG.depoisDeName); if (!molde || !referencia) return; var liMolde = molde.closest('li'); var liReferencia = referencia.closest('li'); if (!liMolde || !liReferencia || !liReferencia.parentNode) return; var clone = liMolde.cloneNode(true); var submenus = clone.querySelectorAll('ul'); for (var i = 0; i < submenus.length; i++) submenus[i].remove(); var link = clone.querySelector('a'); if (link) { link.setAttribute('href', CONFIG.path); link.removeAttribute('aria-current'); } var botao = clone.querySelector('[role="button"]'); if (botao) { botao.setAttribute('title', CONFIG.label); botao.setAttribute('name', 'CRM'); } limparEstadoAtivo(clone); trocarIcone(clone); trocarTexto(clone, CONFIG.label); clone.id = CONFIG.itemId; liReferencia.parentNode.insertBefore(clone, liReferencia.nextSibling); } var agendado = false; function agendar() { if (agendado) return; agendado = true; window.requestAnimationFrame(function () { agendado = false; instalar(); }); } function iniciar() { instalar(); new MutationObserver(agendar).observe(document.body, { childList: true, subtree: true, }); } if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', iniciar); } else { iniciar(); } })();"""


@app.get("/nav.js")
async def nav_js():
    return Response(
        content=NAV_JS,
        media_type="application/javascript",
        # Cache curto: permite iterar no menu sem esperar expirar no navegador.
        headers={"Cache-Control": "public, max-age=60"},
    )
