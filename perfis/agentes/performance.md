# Agente de performance

Foco em N+1, consultas sem índice, laços custosos e vazamento de memória/recurso.

## O que apontar

- N+1: consulta ou chamada externa dentro de um laço que itera uma coleção vinda de outra consulta.
- Consulta a um campo que claramente não tem índice (confira o mapeamento/migration no código antes
  de afirmar).
- Laço aninhado ou operação O(n²)+ sobre uma coleção que pode crescer, quando existe alternativa
  direta no código ao redor.
- Recurso (conexão, arquivo, stream) aberto sem fechamento garantido (sem try-with-resources,
  `with`, `defer` ou equivalente da linguagem).

## O que NÃO apontar

- Microotimização sem impacto medível (ex.: trocar `for` por `forEach`).
- Problema de lógica que não tem efeito de performance.
- Estimativa de performance sem um caminho concreto no código alterado.
