# 02 — Design system

Arquivos: `gui/style.css` (estilos) e `gui/components.py` (componentes).
Cores só por variáveis do libadwaita (`--accent-*`, `--success-*`,
`--warning-*`, `--error-*`, `alpha(currentColor, …)`), então claro, escuro e
alto contraste seguem o desktop.

## Escala

| Item | Valor |
| --- | --- |
| Espaçamento | 6 · 12 · 18 · 24 px (entre grupos 24) |
| Raios | cartão 16 · miniatura 10–12 · selos 999 |
| Largura de conteúdo | `Adw.Clamp` 760 (formulários) · 900–1100 (páginas) · 1200–1400 (galerias/detalhes) |
| Tipografia | `hero-title` 1.9em/800 · `title-4` · `heading` · corpo · `caption` + `dim-label` |

## Componentes

| Componente | Uso |
| --- | --- |
| `DisplayPreview` | moldura neutra de display (`.display-bezel`, igual no claro e no escuro), proporção do painel, quadro real em 1:1 quando cabe (`SCALE_DOWN`), selo (`DEMO` em cor de aviso), rodapé com legenda e **Ampliar** (diálogo que compartilha o mesmo `paintable` ao vivo) |
| `Card` / `CardGrid` | cartão de galeria AshyWall: miniatura do renderizador real, ✓ de seleção (cor de destaque), selo de estado ("Em uso"), título, legenda; `FlowBox` navegável por teclado |
| `StateCard` | estados especiais: ícone, título, explicação e até duas ações (primeira = sugerida) |
| `pill` | estado semântico (sucesso/aviso/erro/destaque) — sempre com texto, nunca só cor |
| `action_tile` | ações rápidas do Início |
| `navigation_page` / `page_layout` | página com `HeaderBar` + conteúdo rolável em clamp |
| `adaptive_split` + `ADAPTIVE` | lado a lado em janelas largas, empilhado abaixo de 1100sp |
| `Thumbnailer` | 1 thread de miniaturas, mais novas primeiro, LRU de 64 |
| `SerialWorker` | chamadas bloqueantes (sysfs, systemctl, diagnóstico) fora da GTK |

## Padrões de interação

- **Edição**: controle → `values` → prévia atualiza → barra inferior
  "Alterações não aplicadas (N)" com **Descartar** / **Aplicar** (Ctrl+S).
- **Confirmações** só para o destrutivo (restaurar padrões; resposta padrão
  "Cancelar"); o resto usa toasts.
- **Erros**: `Adw.AlertDialog` com a mensagem real; cancelamento do Polkit
  vira "A autorização foi cancelada ou negada."
- **Carregando**: spinner na miniatura/prévia até o primeiro quadro.
- **Vazio**: `Adw.StatusPage` com ação ("Procurar novamente").
