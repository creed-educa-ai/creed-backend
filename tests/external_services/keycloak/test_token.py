"""Testes da validação de access token.

Uma chave RSA é gerada no próprio teste e servida como JWKS por um transporte
dublê: assim a validação é exercida de verdade — assinatura, `aud`, `iss` e
`exp` — sem Keycloak e sem chave commitada no repositório.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.external_services.keycloak import token as keycloak_token

KID = "chave-de-teste"
ISSUER = "http://kc.local:8080/realms/creed"

_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_CHAVE.public_key()))
    return {"keys": [{**jwk, "kid": KID, "alg": "RS256", "use": "sig"}]}


def _token(**alteracoes: Any) -> str:
    agora = int(time.time())
    claims: dict[str, Any] = {
        "sub": "11111111-1111-4111-8111-111111111111",
        "email": "dev@creed.local",
        "aud": "creed-backend",
        "iss": ISSUER,
        "exp": agora + 900,
        "iat": agora,
        "realm_access": {"roles": ["admin"]},
    }
    claims.update(alteracoes)
    return jwt.encode(claims, _CHAVE, algorithm="RS256", headers={"kid": KID})


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KEYCLOAK_SERVER_URL", "http://kc.local:8080")
    monkeypatch.setattr(settings, "KEYCLOAK_REALM", "creed")
    monkeypatch.setattr(settings, "KEYCLOAK_CLIENT_ID", "creed-backend")
    monkeypatch.setattr(settings, "KEYCLOAK_JWKS_CACHE_SECONDS", 3600)
    keycloak_token.reset_cache()


def _servir(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[str]:
    """Instala o dublê e devolve a lista de URLs pedidas, para contar chamadas."""
    chamadas: list[str] = []

    def _registrando(request: httpx.Request) -> httpx.Response:
        chamadas.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(
        keycloak_token,
        "build_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_registrando)),
    )
    return chamadas


def _jwks_ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_jwks())


class TestTokenValido:
    async def test_devolve_as_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _servir(monkeypatch, _jwks_ok)

        claims = await keycloak_token.validate_token(_token())

        assert claims["email"] == "dev@creed.local"
        assert claims["realm_access"]["roles"] == ["admin"]

    async def test_le_o_jwks_do_endpoint_do_realm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chamadas = _servir(monkeypatch, _jwks_ok)

        await keycloak_token.validate_token(_token())

        assert chamadas == [
            "http://kc.local:8080/realms/creed/protocol/openid-connect/certs"
        ]


class TestCache:
    async def test_segunda_validacao_nao_relê_o_jwks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem cache, o Keycloak entra no caminho crítico de toda rota protegida."""
        chamadas = _servir(monkeypatch, _jwks_ok)

        await keycloak_token.validate_token(_token())
        await keycloak_token.validate_token(_token())

        assert len(chamadas) == 1

    async def test_ttl_vencido_relê(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chamadas = _servir(monkeypatch, _jwks_ok)
        monkeypatch.setattr(settings, "KEYCLOAK_JWKS_CACHE_SECONDS", 0)

        await keycloak_token.validate_token(_token())
        await keycloak_token.validate_token(_token())

        assert len(chamadas) == 2


class TestTokenRecusado:
    async def test_audiencia_de_outro_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Token emitido para outro destinatário não vale aqui — é o que o
        audience mapper do realm torna conferível."""
        _servir(monkeypatch, _jwks_ok)

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(_token(aud="outro-client"))

    async def test_emissor_de_outro_realm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _servir(monkeypatch, _jwks_ok)

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(
                _token(iss="http://kc.local:8080/realms/outro")
            )

    async def test_expirado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _servir(monkeypatch, _jwks_ok)
        agora = int(time.time())

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(_token(exp=agora - 10, iat=agora - 1000))

    async def test_assinado_por_outra_chave(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _servir(monkeypatch, _jwks_ok)
        intrusa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forjado = jwt.encode(
            {"sub": "x", "aud": "creed-backend", "iss": ISSUER},
            intrusa,
            algorithm="RS256",
            headers={"kid": KID},
        )

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(forjado)

    async def test_sem_kid_no_cabecalho(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _servir(monkeypatch, _jwks_ok)
        sem_kid = jwt.encode({"sub": "x"}, _CHAVE, algorithm="RS256")

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(sem_kid)

    async def test_nao_e_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _servir(monkeypatch, _jwks_ok)

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token("isto-nao-e-um-token")


class TestChaveDesconhecida:
    async def test_relê_o_jwks_uma_vez_antes_de_recusar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`kid` novo normalmente é o realm tendo rodado as chaves, não ataque."""
        chamadas = _servir(
            monkeypatch,
            lambda _r: httpx.Response(200, json={"keys": []}),
        )

        with pytest.raises(keycloak_token.InvalidTokenError):
            await keycloak_token.validate_token(_token())

        assert len(chamadas) == 2


class TestJwksIndisponivel:
    async def test_realm_fora_do_ar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Distinto de token inválido: aqui o problema não é do usuário."""
        _servir(monkeypatch, lambda _r: httpx.Response(503, text="down"))

        with pytest.raises(keycloak_token.JwksUnavailableError):
            await keycloak_token.validate_token(_token())
