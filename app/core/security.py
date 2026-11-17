"""Assinatura dos webhooks que chamam o back (CREED-801).

Quem chama o back de volta assina o corpo com um segredo combinado. Hoje é só o N8N
da esteira de insights, com o `N8N_CALLBACK_SECRET`. Mora em `core/`, e não num
domínio, porque vale para qualquer webhook futuro (playbook
`integrar-servico-externo.md`, "O caminho de volta").

Aqui ficam o cálculo da assinatura e a conferência dela no `Depends` da rota de volta
(CREED-805): ler o corpo cru, recusar timestamp velho e comparar com
`hmac.compare_digest`.
"""

import hashlib
import hmac
import logging
import time
from typing import Annotated, NoReturn

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = "sha256="

# Quanto o relógio de quem assina pode diferir do nosso, para mais ou para menos.
# Passou disso, a chamada é recusada: uma cópia gravada não vale para sempre.
MAX_TIMESTAMP_SKEW_SECONDS = 300


def compute_webhook_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Assinatura `sha256=<hex>` do corpo, no formato do header `X-Creed-Signature`.

    O HMAC-SHA256 é calculado sobre `"{timestamp}.{corpo}"`. O timestamp entra na
    conta para que uma chamada gravada não possa ser reenviada mais tarde com outro
    horário: quem confere recusa timestamp com mais de 5 min.

    `timestamp` é o texto do header `X-Creed-Timestamp` como chegou, e `body` são os
    bytes do corpo como chegaram. O mesmo JSON com outra formatação (espaços, ordem
    das chaves, acento escapado) dá outra assinatura.
    """
    message = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


async def verify_n8n_callback(
    request: Request,
    timestamp: Annotated[
        str | None,
        Header(
            alias="X-Creed-Timestamp",
            description="Segundos Unix do envio, como texto. Entra na assinatura.",
            examples=["1794657600"],
        ),
    ] = None,
    signature: Annotated[
        str | None,
        Header(
            alias="X-Creed-Signature",
            description=(
                "`sha256=` e o HMAC-SHA256 em hexadecimal do `{timestamp}.{corpo}`, "
                "com o segredo combinado com o N8N."
            ),
            examples=[
                "sha256=97b5ac619205daac7077f163620099290f4e2bcd4e985a48d15d49e9989acb3e"
            ],
        ),
    ] = None,
) -> None:
    """Deixa passar só a chamada que o N8N assinou com o segredo combinado.

    Qualquer falha é o mesmo 401 sem detalhe, para quem chama sem direito não aprender
    nada sobre o que errou. O motivo vai ao log, nunca o segredo nem a assinatura.
    """
    secret = settings.N8N_CALLBACK_SECRET
    if not secret:
        # Sem segredo, qualquer um assinaria com a chave vazia: a rota fica fechada.
        _reject("N8N_CALLBACK_SECRET vazio: a rota de volta está fechada")

    if timestamp is None or signature is None:
        _reject("cabeçalho de assinatura ausente")

    try:
        sent_at = int(timestamp)
    except ValueError:
        _reject("timestamp que não é um número")
    if abs(time.time() - sent_at) > MAX_TIMESTAMP_SKEW_SECONDS:
        _reject("timestamp fora da janela de 5 minutos")

    expected = compute_webhook_signature(secret, timestamp, await request.body())
    # Em bytes: `compare_digest` com texto só aceita ASCII e levantaria TypeError
    # (500) diante de um cabeçalho com acento.
    if not hmac.compare_digest(signature.encode("utf-8"), expected.encode("utf-8")):
        _reject("assinatura não confere")


def _reject(reason: str) -> NoReturn:
    logger.warning("Callback do N8N recusado: %s", reason)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida")
