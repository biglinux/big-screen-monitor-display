# 24 — GPU de todos os fabricantes (Fase 2 do roteiro)

## O problema

O uso da GPU vinha só de `/sys/class/drm/cardN/device/gpu_busy_percent`, que só o
driver `amdgpu` cria. Numa NVIDIA com o driver proprietário e numa Intel, o valor
ficava no 0 inicial e era mostrado como medido. A temperatura da NVIDIA também
faltava, porque o driver proprietário não registra hwmon.

## O que mudou

| Fabricante | Uso | Temperatura | VRAM | Frequência | Consumo | Fonte |
| --- | --- | --- | --- | --- | --- | --- |
| AMD | ✅ | ✅ | ✅ | ✅ | ✅ | sysfs/hwmon (como antes) |
| NVIDIA (proprietário) | ✅ | ✅ | ✅ | ✅ | ✅ | **NVML** (`bsmd/nvidia.py`) |
| NVIDIA (nouveau) | — | hwmon, se houver | — | — | — | sysfs |
| Intel (i915/xe) | — | — | — | ✅ | — | `gt/gt0/rps_act_freq_mhz` · `tile0/gt0/freq0/act_freq` |

- Cada GPU tem `vendor`, `pci_slot` e **`usage_known`**. `percent` continua sendo
  número (compatível com todos os temas); `usage_known` diz se ele foi medido.
- `telemetry.gpu_percent_text(gpu)` devolve `"42%"` ou `"—"`. O painel Padrão, o
  GKrellM, os temas antigos (Planet, Computador Antigo, compacto), o Kojiro, o Big
  Media Player e o Brother Away mostram "—" e escondem a barra quando o uso é
  desconhecido.
- O SmartMonitor fotografa um "—" fixo em vez de um campo ao vivo preso em 0.

## Por que NVML em `ctypes`

- **Custo:** `nvidia-smi` a cada segundo cria um processo (~30 ms). A NVML em
  processo leva microssegundos por chamada.
- **Sem dependência nova:** a `libnvidia-ml.so.1` vem com o driver. Sem ela (AMD,
  Intel, nouveau) o módulo nem é carregado, e uma falha é tentada uma vez só.
- **Sandbox:** o serviço tem `DevicePolicy=closed`. Foram liberados só os grupos
  `char-nvidia-frontend` e `char-nvidia` (major 195: `/dev/nvidiactl` e
  `/dev/nvidiaN`). Em máquinas sem NVIDIA o systemd ignora os grupos (verificado
  com `systemd-analyze verify`).

## Por que a Intel continua sem uso

O uso da GPU Intel exige contadores de desempenho (PMU, `CAP_PERFMON`) ou ler o
`fdinfo` de processos de outros usuários. Os dois contrariam o isolamento do
serviço (sem capacidades, `DynamicUser`). Mostrar "—" com a frequência real é mais
honesto do que abrir o sandbox para isso.

## Testes (`tests/test_gpu.py`)

- NVML com uma biblioteca falsa que grava pelos `byref()`: leitura completa, placa
  inexistente, biblioteca ausente e driver não carregado (tentado uma vez só);
  layout das estruturas C.
- `find_gpus` num sysfs falso com AMD, NVIDIA e Intel (fabricante e slot PCI).
- AMD com `gpu_busy_percent`, NVIDIA com e sem NVML, Intel i915 e xe.
- Linha do painel Padrão ("—" e sem barra), métricas do compacto e **todos os
  temas** renderizados com GPU conhecida e desconhecida, em paisagem e retrato.

## Pendente

Validar numa máquina com NVIDIA real (só testado com a biblioteca falsa). Um
relato pelo formulário *Hardware* basta.
