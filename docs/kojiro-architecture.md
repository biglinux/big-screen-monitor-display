# Kojiro — arquitetura

O Kojiro usa a arquitetura de temas existente (`bsmd/themes.py` →
`themes.create("kojiro")`), o mesmo pipeline por display do runtime, a mesma
telemetria compartilhada e os mesmos drivers. Não há aplicativo separado.

```
bsmd/kojiro/
├── model.py      esquema, catálogo de elementos, validação e migração (Python puro)
├── presets.py    as 7 composições prontas
├── layout.py     geometria normalizada, âncoras, layout retrato, alinhar/distribuir/encaixar
├── data.py       telemetria -> métricas (nunca inventa valores), dados de demonstração
├── draw.py       primitivas: anéis, medidores, barras, gráficos, brilho neon, 7 segmentos, pixel
├── widgets.py    um renderizador por tipo/estilo
├── wallpaper.py  arte procedural, imagens importadas, ajustes e efeitos (com cache)
├── assets.py     nome e logotipo da distribuição (os-release + ícones instalados)
├── store.py      papéis de parede, predefinições do usuário, pacotes
└── engine.py     KojiroTheme: composição por camadas, alertas, animações
usr/share/big-screen-monitor-display/
├── kojiro_editor.py   estado do editor (desfazer/refazer) e o canvas Cairo
└── kojiro_page.py     aba Kojiro: barra de ferramentas e inspetor
```

## Composição por camadas

```
base (em cache)      papel de parede + ajustes + efeito de fundo
                     + regiões de vidro fosco + decisões de painel de legibilidade
camadas (em cache)   uma imagem RGBA por elemento, refeita só quando o que ele
                     mostra muda (valores arredondados, fase da animação)
quadro final         cópia da base + camadas na ordem Z -> RGB -> driver
```

- O driver compara quadros (retângulos alterados), então o papel de parede
  só trafega no primeiro quadro; depois, só os números que mudaram.
- Cada elemento tem intervalo de atualização próprio (padrão por tipo,
  configurável) — a métrica é relida só quando vence.
- `KojiroTheme.needs` diz ao coletor quais sensores opcionais ligar
  (ventoinhas, discos por ponto de montagem, processos, endereços IP, sensores
  de temperatura específicos). Com vários displays, o runtime une as
  necessidades: nada é coletado duas vezes e nada é coletado sem um elemento
  visível que o use.

## Alertas

`engine.AlertState` mantém o nível (normal/aviso/crítico) com histerese e
intervalo mínimo; a cor muda gradualmente com o valor (`continuous_level`).
Temperaturas usam o limite do próprio chip (`tempN_crit`/`_max` do hwmon) quando
existe; senão, padrões conservadores (CPU/GPU 95 °C, disco 70 °C) que o usuário
pode alterar. Disco quase cheio ganha borda de atenção; rede intensa aumenta o
brilho das setas; valores críticos pulsam por 8 s e depois ficam estáveis.

## Integração

| Ponto | Mudança |
| --- | --- |
| `settings.py` | chave `kojiro` validada por `kojiro.model`; aceita sobrescrita por display; limite do arquivo 512 KiB; cópia `.bak` do último arquivo válido; um arquivo corrompido não derruba a configuração em execução |
| `themes.py` | `KOJIRO` no registro; o Kojiro tem layout próprio para telas minúsculas |
| `runtime.py` | `wake_collector_needs` lê `theme.needs` a cada ciclo do supervisor |
| `telemetry.py` | coletores sob demanda: ventoinhas (RPM e PWM), discos por ponto de montagem (uso, E/S, temperatura do disco físico), frequência/modelo/núcleos da CPU, limites de temperatura, endereços IP |
| `bsm-helper` | `import-wallpaper` e `remove-wallpaper` |
| polkit | ações `apply-settings`, `display-command`, `import-wallpaper`, `remove-wallpaper` liberadas para o usuário local ativo |
