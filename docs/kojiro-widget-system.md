# Kojiro — sistema de elementos

## Catálogo

| Tipo | Estilos | Dados (de onde vêm) |
| --- | --- | --- |
| `cpu` | anel, semicírculo, arco, anel duplo, medidor, barras, gráficos, texto, HUD | uso total, temperatura (pacote ou sensor escolhido), frequência, modelo |
| `gpu` | idem | uso, temperatura, frequência, VRAM, potência, nome; GPU automática = a de maior VRAM (dedicada) ou índice fixo |
| `ram` / `swap` / `vram` | barras, segmentada, degradê, vertical, termômetro, anel, semicírculo, gráfico, texto | usado/total e %; RAM = memória não recuperável (psutil `used`); sem swap → "sem swap" ou oculto |
| `fan` | ícone girando, anel, texto | RPM; % só pelo PWM (0–255) do mesmo chip — nunca estimada a partir do RPM |
| `encdec` | texto, barra, anel | AMD VCN (codificação+decodificação em um valor); em placas sem esse dado, "—" |
| `disk` | anel, semicírculo, barras, texto, HUD | uso do sistema de arquivos do ponto de montagem; temperatura e E/S do **disco físico** por trás dele |
| `net_down` / `net_up` | texto, gráficos de área/linha/barras, minigráfico | todas as interfaces ou uma escolhida; KB/s, MB/s (bytes) ou Mbps, Gbps (bits) |
| `clock` | moldura futurista, simples, digital | 12/24 h, segundos, data (formato automático pelo idioma ou escolhido), dia da semana, dois-pontos piscando (sem deslocar os dígitos) |
| `distro` | logotipo e nome, só logotipo, só nome | `/etc/os-release` (NAME, ID, LOGO) + ícones instalados; nome curto ("BigLinux"); fallback genérico |
| `cores` | barras, grade de calor | uso por núcleo |
| `processes` | lista | mais ativos por CPU ou memória |
| `uptime`, `hostname`, `kernel`, `ip`, `power`, `battery` | texto (bateria: barra/anel) | sistema |
| `text`, `separator`, `frame` | decorativos | texto livre, linha/linha luminosa/pontos, cantoneiras/caixa/HUD |

Dados ausentes nunca são inventados: o elemento mostra "—" ou some
(*Ocultar quando indisponível*).

## Propriedades comuns

Geometria (x, y, largura, altura normalizados, âncora, rotação), visibilidade,
bloqueio, grupo, cores (principal, secundária, texto), brilho neon, sombra,
opacidade, fonte (padrão, monoespaçada ou qualquer família do sistema via
fontconfig), negrito, tamanho do texto, estilo do texto (normal, monoespaçado,
digital de 7 segmentos, pixel), alinhamento, rótulo, ícone, casas decimais,
unidade, painel de fundo (cor, opacidade, vidro fosco, borda, cantos),
intervalo de atualização, transições suaves, alertas (aviso/crítico,
piscar).

Texto nunca fica abaixo de 8 px: se a caixa é pequena demais, linhas
secundárias são omitidas. Indicadores circulares usam sempre o menor lado da
caixa — não ficam ovais.

## Criar um novo tipo de elemento

1. **Modelo** — em `bsmd/kojiro/model.py`, acrescente a `WIDGET_TYPES`:
   rótulo (com `N_()`), estilos, estilo padrão, tamanho padrão em 800×480,
   intervalo padrão e métrica de alerta (`"temp"`, `"usage"` ou `None`).
   Opções específicas vão em `OPTIONS[tipo]` com (tipo, restrição, padrão).
2. **Dados** — em `bsmd/kojiro/data.py`, escreva `_meu_tipo(widget, opts, stats, now)`
   devolvendo um `Metric` (`available=False` quando o dado não existe) e
   registre em `BUILDERS`. Se precisar de um coletor opcional, declare em
   `needs()` e implemente o coletor em `telemetry.Collector` com uma flag `want_*`.
3. **Desenho** — estilos genéricos (anéis, barras, gráficos, texto, HUD) já
   funcionam. Para um visual próprio, escreva uma função em
   `bsmd/kojiro/widgets.py` e registre em `SPECIAL`.
4. **Interface** — as opções aparecem sozinhas no inspetor (interruptor,
   número, lista ou texto conforme o esquema). Rótulos amigáveis em
   `OPTION_LABELS` de `kojiro_page.py`. O menu "Adicionar elemento" lista os
   tipos agrupados em `_toolbar()`.
5. **Testes** — `test_every_widget_type_and_style_renders` passa a cobrir o
   novo tipo automaticamente; acrescente casos de dados ausentes em
   `tests/test_kojiro.py`.
