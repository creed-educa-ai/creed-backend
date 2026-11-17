"""O instrumento CREED: o conjunto fixo de perguntas que todo período aplica.

Mora aqui, e não em `questions`, porque `forms` também precisa do id (todo período
nasce apontando para ele) e não pode importar `models.py` de outro domínio. A linha
e as perguntas entram por migration de dados, com este mesmo id.
"""

import uuid

CREED_INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000c4ed")
