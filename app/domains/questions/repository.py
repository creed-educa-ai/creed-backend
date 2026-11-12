"""Acesso a dados do dominio questions.

Esta camada NAO contem regra de negocio: so queries. Ordenacao e filtro por
secao sao feitos na propria consulta (ADR: filtro/ordenacao no banco, nunca
em memoria) — por isso list_by_form recebe `section` e monta o where
condicionalmente, em vez de devolver tudo e deixar o service filtrar.

`insert` devolve `None` quando a UniqueConstraint recusa a gravacao — isto
NAO e decisao de negocio, e devolver `None` (nao levantar) e o que
`test_arquitetura.py` exige desta camada: quem decide o que `None` significa
e o service.

Traducoes (EN/ES) ficam em tabelas proprias; o PT vive em `Question.text` e
`QuestionOption.label`. `list_by_form` sempre carrega as alternativas; quando
`lang` e pedido, so a traducao daquele idioma e carregada, da pergunta e das
alternativas (filtro dentro do `selectinload`), sem N+1.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.questions.models import (
    Question,
    QuestionLang,
    QuestionOption,
    QuestionOptionTranslation,
    QuestionSection,
    QuestionTranslation,
)


class QuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, question: Question) -> Question | None:
        """Grava uma pergunta no banco.

        Devolve `None` se a posicao foi ocupada entre a checagem do service
        e este `flush()` — corrida sem lock, fechada pela UniqueConstraint.
        """
        self.db.add(question)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_questions_form_id_order_index" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(question)
        return question

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        result = await self.db.execute(select(Question).where(Question.id == question_id))
        return result.scalar_one_or_none()

    async def list_by_form(
        self,
        form_id: uuid.UUID,
        section: QuestionSection | None = None,
        lang: QuestionLang | None = None,
    ) -> list[Question]:
        query = select(Question).where(Question.form_id == form_id)

        if section is not None:
            query = query.where(Question.section == section)

        if lang is None:
            query = query.options(selectinload(Question.options))
        else:
            query = query.options(
                selectinload(
                    Question.translations.and_(QuestionTranslation.lang == lang)
                ),
                selectinload(Question.options).selectinload(
                    QuestionOption.translations.and_(
                        QuestionOptionTranslation.lang == lang
                    )
                ),
            )

        query = query.order_by(Question.order_index)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_required(self, form_id: uuid.UUID) -> list[Question]:
        """Obrigatorias do formulario, em ordem de posicao; o filtro e no banco."""
        result = await self.db.execute(
            select(Question)
            .where(
                Question.form_id == form_id,
                Question.required.is_(True),
            )
            .order_by(Question.order_index)
        )
        return list(result.scalars().all())

    async def get_by_form_and_order(
        self, form_id: uuid.UUID, order_index: int
    ) -> Question | None:
        result = await self.db.execute(
            select(Question).where(
                Question.form_id == form_id,
                Question.order_index == order_index,
            )
        )
        return result.scalar_one_or_none()

    async def delete_by_forms(self, form_ids: list[uuid.UUID]) -> None:
        """Apaga as perguntas dos formularios e, antes, as alternativas delas.

        As duas tabelas sao deste dominio, entao a ordem mora aqui: a alternativa
        aponta para a pergunta, e o banco recusaria apagar a pergunta primeiro.
        """
        if not form_ids:
            return
        questions_of_forms = select(Question.id).where(Question.form_id.in_(form_ids))
        await self.db.execute(
            delete(QuestionOption).where(
                QuestionOption.question_id.in_(questions_of_forms)
            )
        )
        await self.db.execute(delete(Question).where(Question.form_id.in_(form_ids)))


class QuestionTranslationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(
        self, translation: QuestionTranslation
    ) -> QuestionTranslation | None:
        """Grava a traducao de uma pergunta.

        Devolve `None` se (question_id, lang) ja existe: a UniqueConstraint fecha
        a corrida que a checagem do service sozinha nao fecha.
        """
        self.db.add(translation)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_question_translations_question_id_lang" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(translation)
        return translation

    async def get_by_question_and_lang(
        self, question_id: uuid.UUID, lang: QuestionLang
    ) -> QuestionTranslation | None:
        result = await self.db.execute(
            select(QuestionTranslation).where(
                QuestionTranslation.question_id == question_id,
                QuestionTranslation.lang == lang,
            )
        )
        return result.scalar_one_or_none()


class QuestionOptionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, option: QuestionOption) -> QuestionOption | None:
        """Grava uma alternativa no banco.

        Devolve `None` se a posição foi ocupada entre a checagem do service e este
        `flush()`: a UniqueConstraint fecha a corrida que a checagem sozinha não fecha.
        """
        self.db.add(option)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_question_options_question_id_order_index" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(option)
        return option

    async def get_by_id(self, option_id: uuid.UUID) -> QuestionOption | None:
        result = await self.db.execute(
            select(QuestionOption).where(QuestionOption.id == option_id)
        )
        return result.scalar_one_or_none()

    async def get_by_question_and_order(
        self, question_id: uuid.UUID, order_index: int
    ) -> QuestionOption | None:
        result = await self.db.execute(
            select(QuestionOption).where(
                QuestionOption.question_id == question_id,
                QuestionOption.order_index == order_index,
            )
        )
        return result.scalar_one_or_none()


class QuestionOptionTranslationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(
        self, translation: QuestionOptionTranslation
    ) -> QuestionOptionTranslation | None:
        """Grava a traducao de uma alternativa.

        Devolve `None` se (option_id, lang) ja existe.
        """
        self.db.add(translation)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_question_option_translations_option_id_lang" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(translation)
        return translation

    async def get_by_option_and_lang(
        self, option_id: uuid.UUID, lang: QuestionLang
    ) -> QuestionOptionTranslation | None:
        result = await self.db.execute(
            select(QuestionOptionTranslation).where(
                QuestionOptionTranslation.option_id == option_id,
                QuestionOptionTranslation.lang == lang,
            )
        )
        return result.scalar_one_or_none()
