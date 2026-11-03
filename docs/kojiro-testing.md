# Kojiro — testes

`python3 -m pytest -q tests` — 617 testes, sem hardware.

| Arquivo | O que cobre |
| --- | --- |
| `tests/test_kojiro.py` (156) | validação e reparo de configurações hostis, limite de elementos, ids duplicados, migração; sobrescrita por display; recuperação de arquivo corrompido e `.bak`; geometria (ida e volta pixel↔normalizado para todas as âncoras e 5 resoluções, ultrawide, proporção igual), layout retrato, alinhar/distribuir/encaixar/sobreposição; dados ausentes (ventoinha, VCN, swap, GPU, disco), % de ventoinha só por PWM, GPU automática dedicada, limites de temperatura do hardware, bits × bytes; alertas com histerese e intervalo mínimo, cor gradual; as 7 predefinições em 8 resoluções (incluindo retrato, quadrada, ultrawide e micro); todos os tipos × todos os estilos; ordem Z; cache de camadas; registro do tema; 8 papéis de parede incluídos; 6 modos de ajuste com todos os ajustes; papel de parede ausente; verificação estrutural de PNG (assinatura, CRC, IEND, dimensões); deduplicação e limite de papéis de parede; normalização de JPEG/WebP/BMP/GIF/PNG e rejeição de arquivos falsos; predefinições do usuário e exportação JSON; pacotes com e sem imagem, entradas maliciosas (`../`), bomba de compressão; coleta sob demanda no runtime |
| `tests/test_kojiro_editor.py` (9) | seleção, mover, desfazer/refazer, coalescência, adicionar/duplicar/excluir, grupos, bloqueio, alinhar, camadas, copiar/colar estilo, layout retrato materializado na primeira edição, predefinições e paletas desfazíveis, nova resolução de referência sem mover nada |
| `tests/test_helper.py` (+7) | `import-wallpaper` válido (modo 0644), não-PNG rejeitado, ids de remoção maliciosos rejeitados |
| `tests/test_responsive.py`, `tests/test_themes.py` | o Kojiro entra automaticamente nas matrizes de temas × resoluções × orientações × tela redonda |

## Validação manual feita

- Janela real: arrastar um elemento (60 px), Shift+seta (10 px), desfazer,
  importar uma foto 2400×1350 como papel de parede, aplicar predefinição
  mantendo a foto, exportar e reler pacote com imagem, **Aplicar** gravando as
  configurações — tudo pela interface (`BSM_CONFIG` de desenvolvimento).
- Serviço com o layout salvo em dois displays simulados (paisagem e retrato).
- **Hardware real (AX206 800×480)**: Kojiro Cyberpunk por 75 s via serviço
  empacotado, com e sem animações (medições em kojiro-performance.md).
- Caminho Polkit real: `pkexec bsm-helper display-command` como usuário ativo,
  sem senha, padrão exibido no display.

Só o AX206 foi testado fisicamente; os demais displays usam o mesmo motor e
foram validados com o simulador.
