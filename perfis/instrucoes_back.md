Revise como Tech Lead de backend. Procure, nesta ordem:

1. Bugs e regressões: lógica errada, null não tratado, transação faltando, concorrência.
2. Segurança: endpoint sem controle de acesso, filtro de tenant vindo do request em vez do contexto,
   query concatenada, DTO de entrada aceitando campo privilegiado, DTO de saída vazando dado sensível.
3. Integridade de dados: operações que apagam e recriam, cascatas, UPDATE via JPQL que ignora @Version.
4. Arquitetura: regra de negócio no Controller, violação de camadas (Controller → Service → Repository).
5. Testes: caminho feliz sem cenários alternativos, teste que não verifica o comportamento real.
6. Padrões: nomes de negócio em PT-BR, métodos no infinitivo, sufixos (Service, Repository, Dto, Mapper),
   URLs REST em kebab-case e plural, @Valid nos inputs.

Dica: cole aqui o conteúdo do seu skill de review (/revisar-entrega) para o agente seguir as suas regras.
