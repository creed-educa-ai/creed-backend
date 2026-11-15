"""Cliente do webhook de ida da esteira de insights (CREED-803).

Só transporta: recebe o pedido já montado pelo `InsightService` e o entrega ao N8N.
Não sabe o que é um insight nem o que fazer quando a entrega falha. Quem decide é o
worker (CREED-804), por isso não há retentativa aqui: um laço escondido no client
multiplicaria disparos sem ninguém ver.

O N8N responde `202` antes de processar (spec da CREED-80, "Ida: back → N8N"), então
"entregue" quer dizer só que o pedido chegou. O texto volta depois, pelo callback
assinado (CREED-805).
"""

import httpx

from app.core.config import settings
from app.external_services.n8n.exceptions import N8NUnavailableError
from app.external_services.n8n.schemas import IndividualInsightRequest


class N8NClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        # O `AsyncClient` vem pronto de quem chama: o worker mantém um aberto entre
        # os ciclos e o fecha no desligamento. Nunca criado em nível de módulo.
        self.http = http

    async def dispatch(self, payload: IndividualInsightRequest) -> None:
        """Entrega o pedido ao webhook. Qualquer `2xx` é sucesso.

        Levanta `N8NUnavailableError` para `4xx`, `5xx`, tempo esgotado e erro de
        conexão. Nenhuma exceção do `httpx` sai daqui.
        """
        try:
            response = await self.http.post(
                settings.N8N_WEBHOOK_URL,
                json=payload.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {settings.N8N_WEBHOOK_TOKEN}"},
                # Por chamada, e não só no `AsyncClient`: o tempo máximo vale mesmo
                # que quem criou o client tenha esquecido de configurá-lo.
                timeout=settings.N8N_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            # Tempo esgotado, DNS, conexão recusada, URL sem protocolo.
            raise N8NUnavailableError(
                f"N8N não respondeu: {type(exc).__name__}: {exc}"
            ) from exc

        if not response.is_success:
            raise N8NUnavailableError(
                f"N8N respondeu {response.status_code}: {response.text[:200]}"
            )
