# Kojiro — papéis de parede

## Fontes

| Fonte | Valor em `wallpaper.source` |
| --- | --- |
| Arte incluída | `builtin:cyberpunk`, `neon_grid`, `minimal`, `matrix`, `retro`, `dark`, `glass`, `industrial` |
| Imagem importada | `user:<32 hex>` |
| Cor sólida | `color` |
| Degradê | `gradient` (duas cores + ângulo) |

A arte incluída é **gerada pelo aplicativo** (Pillow + NumPy) na proporção do
display: nenhuma imagem de terceiros, nada para recortar, nítida em qualquer
resolução. Exemplo: o Cyberpunk desenha céu em degradê, portal neon central,
duas camadas de prédios com janelas acesas, vigas metálicas e grade em perspectiva.

## Importação segura

1. A janela abre o arquivo **como o usuário** (`store.normalize_image`):
   tamanho máximo do arquivo 64 MiB, até 50 Mpx (proteção contra
   "bombas de descompressão"), formato reconhecido pelo conteúdo (não pela
   extensão), primeiro quadro de GIF/WebP animados, orientação EXIF aplicada,
   metadados removidos, lado maior reduzido para 2560 px, recodificado em PNG
   (≤ 8 MiB). SVG é rasterizado com `rsvg-convert` também como usuário.
2. O assistente privilegiado (`bsm-helper import-wallpaper`) **não decodifica**
   a imagem como root: só confere a estrutura PNG (assinatura, IHDR, CRC de
   cada bloco, IEND, dimensões 16–4096 px) e grava `<sha256>.png` em
   `/etc/big-screen-monitor-display/wallpapers/` com modo 0644, sem seguir
   links simbólicos. Limite de 64 imagens; conteúdo idêntico não duplica.
3. Quem decodifica é o serviço, sem privilégios e em sandbox.

O arquivo original nunca é alterado nem referenciado: o serviço não lê `/home`.
Em execução de desenvolvimento (`BSM_CONFIG`), a pasta é `wallpapers/` ao lado
do arquivo de configurações.

## Ajustes

Ajuste (preencher/recortar, inteira, esticar, centralizar, repetir, tamanho
original), zoom 100–400%, deslocamento horizontal/vertical, rotação de 90° em 90°,
espelhar, inverter, brilho, contraste, saturação, gama, desfoque, escurecer,
cor e intensidade de sobreposição, vinheta e degradê de proteção para textos
(base, topo, laterais ou topo+base). Efeitos de fundo: linhas de varredura,
grade e pontos. O resultado fica em cache e só é refeito quando um desses
valores ou o tamanho do display muda.

## Transparência simulada

Displays LCD não são transparentes. A predefinição **Vidro** simula painéis
translúcidos: cada elemento pode desfocar o papel de parede atrás de si
(`frost`, calculado uma vez na camada de base) e ter painel claro
semitransparente com borda fina.
