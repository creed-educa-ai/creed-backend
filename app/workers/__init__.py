"""Processos que rodam fora da requisição, cada um no seu container (ADR-0010).

Irmão de `domains/` e de `external_services/`. Um worker é porta de entrada, como
uma rota: abre a unidade de trabalho, chama o service do domínio e mais nada.
"""
