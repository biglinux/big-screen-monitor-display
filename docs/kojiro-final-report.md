# Kojiro — relatório final (4.2.0)

## Entregue

| Critério | Situação |
| --- | --- |
| Tema integrado e selecionável | ✅ `kojiro` no registro de temas, na galeria e por display |
| Upload de papel de parede | ✅ PNG/JPEG/WebP/BMP/GIF/TIFF/SVG, importação segura, galeria com remoção |
| Imagem de fundo no display | ✅ validado no AX206 real |
| Elementos obrigatórios | ✅ RAM, SWAP, CPU, GPU, FAN, ENC/DEC, HDD, DN, UP, relógio, logotipo+nome da distro |
| Elementos extras | ✅ VRAM, núcleos, processos, tempo ligado, nome do computador, kernel, IP local, bateria, perfil de energia, texto, separador, moldura |
| Elementos independentes, posição e tamanho | ✅ camadas, geometria normalizada com âncoras |
| Editor visual | ✅ arrastar, redimensionar, encaixe, guias, grade, margens, sobreposições, seleção múltipla, grupos, bloqueio, alinhar, distribuir, camadas, copiar/colar estilo, desfazer/refazer, atalhos, menu de contexto |
| Aba exclusiva | ✅ aba Kojiro com inspetor de 6 seções |
| Predefinições | ✅ 7 + predefinições do usuário + exportar/importar `.json` e `.kojiro.zip` |
| Detecção da distribuição | ✅ os-release + ícones instalados, nome curto, fallback |
| Sensores reais e dados ausentes | ✅ nada é inventado; "—" ou ocultar |
| Resoluções | ✅ 80×160 a 1920×720, retrato automático, ultrawide, micro, círculos sempre redondos |
| Persistência e tempo real | ✅ validação, migração, `.bak`, proteção contra arquivo corrompido, aplicação em 1 s, *Ao vivo no display*, sem senha para alterações visuais |
| Desempenho | ✅ 1,5% de CPU estático / 7,5% animado no AX206; memória estável |
| Testes | ✅ 617 no total (193 a mais que a 4.1) |
| Traduções | ✅ 929 mensagens em português |
| Empacotamento | ✅ PKGBUILD atualizado (`python-cairo`, `fontconfig`), instalado e testado |
| README | ✅ seção Kojiro com capturas |
| Temas existentes | ✅ sem regressão (todos os testes anteriores passam) |

## Decisões técnicas

- **Arte procedural** em vez de imagens de terceiros: sem problemas de
  licença, nítida em qualquer proporção, 8 KB de código por papel de parede.
- **Decodificação só sem privilégios**: a janela normaliza como usuário; o
  root apenas confere a estrutura PNG; o serviço sandbox decodifica.
- **Polkit por verbo** (`exec.argv1`): alterações visuais sem senha para o
  usuário local ativo; controle do serviço continua com administrador.
- **Âncoras + escala uniforme** em vez de coordenadas puramente relativas:
  preserva a composição e mantém círculos redondos e texto legível.
- **Cairo só no editor**; o serviço usa Pillow (já era dependência).

## Limitações honestas

- As duas imagens de referência citadas no pedido não chegaram junto com o
  texto; a predefinição Cyberpunk segue a descrição detalhada (posições,
  cores e tipos de indicador).
- FPS de jogos não é exibido: não existe fonte confiável no sistema.
- Codificação/decodificação de vídeo só em GPUs AMD (VCN, valor combinado);
  Intel e NVIDIA não expõem esse dado pelo caminho atual.
- GIF/WebP animados usam o primeiro quadro (animação desligada por eficiência).
- Rotação livre de elementos existe para todos os tipos; em texto pequeno a
  rotação reduz a nitidez.
- Validação física apenas no AX206.
