"""Assinatura dos webhooks que chamam o back (CREED-801).

Quem chama o back de volta assina o corpo com um segredo combinado. Hoje é só o N8N
da esteira de insights, com o `N8N_CALLBACK_SECRET`. Mora em `core/`, e não num
domínio, porque vale para qualquer webhook futuro (playbook
`integrar-servico-externo.md`, "O caminho de volta").

Aqui fica só o cálculo. A conferência (ler o corpo cru, recusar timestamp velho e
comparar com `hmac.compare_digest`) é o `Depends` da CREED-805.
"""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


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
