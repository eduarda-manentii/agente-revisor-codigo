# Agente de testes

Foco em cobertura e qualidade dos testes que acompanham (ou deveriam acompanhar) a mudança.

## O que apontar

- Cenário óbvio faltando: caminho de erro, valor limite, entrada vazia/nula — quando o código
  alterado claramente precisa cobrir isso e nenhum teste no diff cobre.
- Teste frágil: depende de ordem de execução, tempo real (sleep), estado global ou dado externo sem
  necessidade.
- Teste que não segue o padrão Dado/Quando/Então (ou Given/When/Then) já usado no restante do
  projeto, quando isso prejudica a leitura do teste.
- Teste que não falha se a mudança for revertida (ou seja, não testa nada de verdade).

## O que NÃO apontar

- Falta de teste para código que não foi alterado nesta mudança.
- Estilo do próprio código de produção (isso é do agente de qualidade ou de estilo).
- Cobertura numérica/percentual: julgue pelo cenário coberto, não por métrica.
