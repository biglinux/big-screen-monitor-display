# PLANNING.md — Status do roteiro anterior

O roteiro original (versão 3.x) foi executado na 4.0. A documentação técnica
atual está em [`docs/`](docs/); este arquivo só registra o destino de cada item.

| Item do roteiro 3.x | Status 4.0 |
| --- | --- |
| Criar suíte de testes | ✅ 191 testes em `tests/` + CI (`.github/workflows/tests.yml`) |
| `subprocess.run` bloqueando a GTK | ✅ operações administrativas e diagnóstico em threads |
| `sensors` a cada segundo | ✅ sensor da CPU lido direto no sysfs (o `powerprofilesctl` a cada 0,4 s também saiu) |
| Toasts × HIG | ℹ️ revisto: *toasts* são o padrão recomendado pela HIG do GNOME/libadwaita para retorno passageiro; erros usam diálogos |
| Lock em `SYSTEM_STATS` | ✅ coleta em `bsmd/telemetry.py` com `STATS_LOCK` e `snapshot()` |
| `except:` nus | ✅ removidos (`except Exception` com contagem de erros por coletor) |
| `lspci` sem timeout | ✅ lista de argumentos, sem shell, timeout de 3 s, executado uma vez |
| Imports não usados / `ruff` | ✅ código novo passa no `ruff` (E, F, W, B) |
| `Image.ANTIALIAS` | ✅ não usado |
| Confirmação em "Restaurar padrões" | ✅ diálogo; nada muda no display até "Aplicar" |
| Rótulos acessíveis (Orca) | ✅ definidos; ⏳ teste real com Orca pendente |
| Cache de SVG | ✅ cache positivo e negativo (não chama `rsvg-convert` a cada quadro) |
| Separar o monitor em módulo próprio | ✅ `bsmd/` (telemetria, drivers, runtime, temas, saúde) |
