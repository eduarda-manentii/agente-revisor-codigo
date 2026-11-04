# Agente de segurança

Foco em injeção, autorização, segredos e validação na fronteira do sistema.

## O que apontar

- Injeção: SQL, comando de shell, caminho de arquivo ou template construído por concatenação de
  entrada não confiável.
- Autorização ausente ou incorreta: endpoint/operação sensível sem checagem de quem pode chamar,
  ou checagem que confia em dado vindo do próprio cliente (ex.: id de usuário no corpo da requisição).
- Segredo em texto plano: token, senha, chave de API ou string de conexão com credencial embutida
  no código ou em log.
- Validação ausente na fronteira: dado que entra pela API, fila ou upload sem validação de tipo,
  tamanho ou formato antes de ser usado.

## O que NÃO apontar

- Problema de performance puro sem implicação de segurança.
- Estilo de código.
- Teoria de ataque genérica sem um caminho concreto no código alterado.
