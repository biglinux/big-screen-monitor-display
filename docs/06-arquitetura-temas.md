# 06 — Arquitetura de temas

```
Hardware collectors (bsmd/telemetry.py)
        │ SYSTEM_STATS / snapshot()
        ▼
Theme.render(width, height, settings, ctx)  ← bsmd/themes.py (registro)
        │ PIL.Image na orientação lógica
        ▼
frames.to_native()  (rotação para o painel)
        ▼
Driver.present()  → RGB565 → dirty rects → USB/serial   (bsmd/drivers.py)
```

Os temas não conhecem drivers. A janela de configuração usa **os mesmos
objetos** para a prévia, inclusive sem display conectado.

## Contrato de um tema

```python
class MeuTema:
    info: ThemeInfo                 # id, nome, descrição, autor, animado, orientações,
                                    # resoluções, recursos, preferências
    def render(self, width, height, settings, ctx) -> PIL.Image: ...
    def frame_interval(self, settings, ctx) -> float: ...   # segundos até o próximo quadro
    def close(self): ...
```

`ctx` (`RenderContext`) oferece `target_fps` (decidido pelo runtime),
`on_battery`, `state_dir`, `preview` e `telemetry()`.

## Registro

`themes.REGISTRY` mantém os metadados; `themes.create(id, ctx)` instancia e
**cai para Dark** se o id não existir ou se o tema falhar ao carregar. O runtime
também troca para Dark após 3 falhas seguidas de render, registrando incidente.

| id | Módulo | Observações |
| --- | --- | --- |
| `standard` | `dashboard.py` | 8 esquemas (`std_scheme`); substitui Dark/Light/Neon/Cyberpunk |
| `gkrellm` | `gkrellm.py` | módulos medidos, preferências `gk_*` |
| `planet` | `legacy_themes.py` | posições reais de Sol/Lua, preferências `planet_*` |
| `old_computer` | `legacy_themes.py` | preferências `oc_*` |
| `brother_away` | `brother_away/` | animado + narrativo, preferências `ba_*` e `overlay_*` |

Os ids antigos `dark`, `light`, `neon` e `cyberpunk` continuam aceitos: a
validação das configurações os converte em `standard` com o esquema
correspondente, e `themes.create()` também os aceita diretamente.

## Revisão visual (4.0)

Problemas encontrados ao renderizar todos os temas em 320×240, 480×320,
800×480 e nas versões em retrato:

| Tema | Problema | Solução |
| --- | --- | --- |
| Dark/Light/Neon/Cyberpunk | título sobre o relógio, taxas de rede sobre o relógio, temperatura colada na % da CPU, nome da GPU sobre "CORE", texto minúsculo em 320×240 | tema Padrão novo: cada texto é medido (`fit()` com reticências), itens opcionais saem por prioridade, fontes derivam do espaço disponível |
| GKrellM | fontes fixas (16/20/26 px) colidindo em colunas estreitas; PPP/VLAN/inet0 desenhavam o histórico da CPU como tráfego; "sys" mostrava voltagens fixas sem sensores; dispositivos eram uma lista fixa | módulos que medem a própria altura; fonte monoespaçada (DejaVu Sans Mono incluída) proporcional à coluna; módulos que não cabem são omitidos; dados reais por interface (`net_ifaces`), sensores e ventoinhas reais (`sensors`), montagens removíveis reais |
| Planet | piso de escala 0,58 desenhava o layout de 464×278 numa tela de 320×240; no retrato o título cortado atrás do cartão; RAM "total / usado"; anel de % sobreposto; "SUNNY / WIND 3 / 22°C" e "VOLUME 28%" fixos; "GPU CLOCK" sempre "--" | renderização na escala mínima de projeto + redução proporcional; título posicionado pela altura real da fonte; ordem correta; % fora do anel quando não cabe; tempo ligado/host e uso do disco; clock real via `pp_dpm_sclk` |
| Computador Antigo | `ValueError` em 240×320 (ícones com margens fixas de 12 px); `CPU92%` sobreposto em 320×240; "HISTORY 60S" (são 30 amostras) e "O: OVERLAY" (atalho inexistente) | ícones proporcionais com tamanho mínimo seguro; escala mínima + redução; cartões sem espaço omitem rodapé/modelo; textos corretos |
| Todos | `get_svg_icon()` corrompia cores começando com `ff…f` (`#ffff00` → `#ffff0000`) e o ícone sumia | substituição única e exata da cor |

## Abas de configuração por tema

`config_gui.py` cria uma aba para cada tema (`THEME_PAGES`). Apenas a do tema
**aplicado** (salvo) fica visível; ao aplicar outro tema a aba troca e um aviso
oferece "Personalizar". Cada aba tem sua própria prévia, renderizada com o
mesmo objeto de tema do serviço.

## Como adicionar um tema

1. Crie a classe com o contrato acima (veja `LegacyTheme` e `BrotherAwayTheme`).
2. Registre um `ThemeInfo` em `bsmd/themes.py` e trate o id em `create()`.
3. Acrescente o id em `settings.THEME_IDS`.
4. Crie a aba em `config_gui.py` (`THEME_PAGES`) e as chaves no esquema.
5. Inclua o tema em `tests/test_themes.py` (todas as resoluções e opções).

## Compatibilidade

`main.py` mantém `get_settings()`, `render_dashboard()`,
`get_theme_colors()` e `SYSTEM_STATS` para scripts que importavam o módulo 3.x.
