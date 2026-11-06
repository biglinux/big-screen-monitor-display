# 04 — Implementação

## Arquivos

| Arquivo | Mudança |
| --- | --- |
| `bsmd/displays/base.py` | `Capabilities.output/metrics/display`, `TelemetryDriver` |
| `bsmd/displays/deepcool/*` | Pacote novo (protocolos, modelos, métricas, hid, drivers, conflitos, prévia) |
| `bsmd/displays/discovery.py` | `UsbDevice.hidraws`; opções `dc_lead_zeros`, `dc_rotation` |
| `bsmd/displays/registry.py` | Perfis `deepcool_*` (validação B) |
| `bsmd/telemetry.py` | Potência (RAPL/zenergy/amd_energy), frequência máxima, preferência de sensor, idade das leituras |
| `bsmd/runtime.py` | Ramo de telemetria nos laços de render/transporte; `status.metrics` |
| `bsmd/settings.py` | Chaves `dc_*` (globais e por display) |
| `gui/deepcool_page.py`, `displays_page.py`, `config_gui.py`, `gui/dashboard.py` | Interface |
| `usr/lib/udev/rules.d/70-big-screen-monitor-display.rules` | hidraw/USB DeepCool e RAPL restritos ao grupo do serviço |
| `usr/lib/systemd/system/big-screen-monitor-display.service` | `DeviceAllow=char-hidraw rw` |
| `pkgbuild/pkgbuild.install` | `udevadm trigger` para `3633`, `hidraw` e `powercap` |

## Configurações (`dc_*`)

| Chave | Valores | Padrão | Efeito |
| --- | --- | --- | --- |
| `dc_preset` | auto, essentials, advanced, guardian, performance, minimal, custom | auto | Apresentação; *auto* segue o tema |
| `dc_main` | auto, temp, usage, power | auto | Campo configurável (preset Custom, coolers de campo único) |
| `dc_temp_unit` | c, f | c | Unidade (AG é só °C; MYSTIQUE desenha °C) |
| `dc_alarm` | bool | true | Luz de alarme por software (AK, AG, LS) |
| `dc_alarm_temp` | 60–100 | 90 | Limite do alarme por software |
| `dc_interval` | 0.5, 1, 2, 3, 5 | 1 | Intervalo de atualização (mínimo da família respeitado) |
| `dc_freq_source` | max, average | max | Frequência enviada ao AK PRO / MYSTIQUE |
| `dc_rotation` | 0, 90, 180, 270 | 0 | MYSTIQUE (reabre o dispositivo) |
| `dc_lead_zeros` | bool | true | LD (reabre o dispositivo) |

## Regras de valores

* `metrics.gather()` devolve `None` + motivo para tudo que não é real:
  sensor ausente, leitura velha (> 6 s), contador de energia sem permissão
  ou aquecendo, frequência não informada, GPU sem sensor.
* Coolers de campo único (AK, AG, LS) **nunca** mostram uma métrica
  indisponível: o campo passa para uma que exista.
* Modo *auto* do campo único alterna a cada 5 s, como o software oficial.
* Coolers de layout fixo recebem 0 no campo indisponível (não há "em
  branco"), registrado em `missing`.
* A conversão para °F acontece só no `Frame`; a métrica interna é sempre °C.

## Runtime

* `_render_loop`: se o driver é de telemetria, fecha o tema (não renderiza
  imagem nenhuma), chama `_telemetry_step()` e espera
  `max(driver.min_interval, dc_interval)`.
* `_transport_loop`: um `Frame` só é apresentado a uma sessão de
  telemetria; imagens nunca chegam a um cooler.
* Padrões de teste, introdução e quadro de "parado" são ignorados para
  coolers.
* `status()` inclui `metrics`: campos enviados, campo atual, alarme,
  ausentes, motivos, fontes dos sensores e horário da última atualização.

## Recuperação

A desconexão (`ENODEV`) vira `DISCONNECTED`; o runtime reabre o nó quando
ele reaparece e repete a inicialização (por exemplo, os dois pacotes do LD
— verificado em `test_runtime_recovers_a_cooler_that_vanished`).

## Permissões

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3633", ATTRS{idProduct}=="0001|0002|0003|0004|0006|0008|000a|0010|0011|0012", MODE="0660", GROUP="big-screen-monitor", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="3633", ATTR{idProduct}=="0009", MODE="0660", GROUP="big-screen-monitor", TAG+="uaccess"
ACTION=="add|change", SUBSYSTEM=="powercap", KERNEL=="intel-rapl:[0-9]", RUN+="/usr/bin/chgrp big-screen-monitor /sys%p/energy_uj", RUN+="/usr/bin/chmod 0440 /sys%p/energy_uj"
```

* Somente os PIDs suportados, nunca todo `hidraw`, nunca `0666`.
* RAPL: leitura (0440) apenas para o grupo do serviço, somente nos domínios
  de pacote. As permissões globais dos sensores de energia não mudam.
* Teste automático garante que a lista de PIDs do udev é exatamente a dos
  modelos suportados e que não há `0666` fora de comentários.
