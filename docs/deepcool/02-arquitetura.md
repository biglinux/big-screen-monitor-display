# 02 — Arquitetura

## Dois tipos de saída no mesmo contrato

`Capabilities.output` distingue:

* `raster` — painéis LCD: o runtime renderiza o tema e chama
  `driver.present(image)` (inalterado);
* `telemetry` — coolers DeepCool: o runtime monta um `Frame` de métricas e
  chama `driver.present(frame)`.

`TelemetryDriver` (`bsmd/displays/base.py`) é a base dos drivers de
telemetria: tamanho nativo `(0, 0)`, sem brilho, `encoding="metrics"`,
`min_interval` próprio da família.

Todo o resto do runtime é reaproveitado sem bifurcação: máquina de estados
do link (starting → healthy → degraded → recovering …), backoff, watchdog
de heartbeats, isolamento por display, comandos `reconnect`, status JSON.

```
telemetry.Collector ──snapshot──► metrics.gather() ──Values──► metrics.build_frame()
   (1 s, compartilhado)              (None + motivo)               (preset, tema, unidade, alarme)
                                                                         │ Frame
                                                                         ▼
                                     DisplaySession._render_loop ──mailbox──► _transport_loop
                                                                               driver.present(frame)
                                                                               ├─ DeepCoolHid  (hidraw)
                                                                               └─ DeepCoolMystique (pyusb)
```

## Pacote `bsmd/displays/deepcool/`

| Módulo | Responsabilidade | I/O |
| --- | --- | --- |
| `protocols.py` | Construtores de pacotes puros (AK, AG, LS, AK PRO, LD, MYSTIQUE) | Nenhum |
| `models.py` | Famílias, PIDs, nomes, estado nos projetos de referência | Nenhum |
| `metrics.py` | Valores, presets, adaptador de temas, compatibilidade, `Frame` | Nenhum |
| `hid.py` | Abertura segura de `hidraw` (ioctl de identidade + `flock`) | hidraw |
| `drivers.py` | `DeepCoolHid`, `DeepCoolMystique`, `create()` | hidraw / USB |
| `conflicts.py` | Processos e units conhecidos de outros programas DeepCool | Leitura de `/proc` e unit files |
| `preview.py` | Desenho da face do cooler para a interface (nunca enviado) | Nenhum |

A interface fica em `gui/deepcool_page.py` (cartão, página de detalhe,
diagnóstico, prévia no painel inicial).

## Fluxo de detecção

1. `discovery.scan_usb()` lê o sysfs e agora também lista
   `…/<interface>/<hid>/hidraw/hidrawN`.
2. `registry._deepcool_profiles()` cria um perfil por família com
   `Rule(0x3633, PIDs, CONFIRMED)` — VID/PID exatos, confiança "confirmado".
3. `Profile.create()` despacha `deepcool_*` para `drivers.create()`.
4. `DeepCoolHid.open()` confere a identidade do nó por ioctl antes do
   primeiro byte e trava o nó com `flock(LOCK_EX|LOCK_NB)`.

Nenhuma sondagem às cegas: um PID desconhecido do fabricante `3633` é
listado na interface como "Outros dispositivos DeepCool" e nada é enviado.

## Telemetria nova (`bsmd/telemetry.py`)

* Temperatura: preferência `Tdie` > `Tctl` > `Package id 0`
  (k10temp/zenpower/coretemp); `cpu_temp_at` marca a idade da leitura e
  valores com mais de `FRESH_FOR = 6 s` são descartados.
* Frequência: `highest_core_mhz()` (máximo de `scaling_cur_freq`, com
  `/proc/cpuinfo` como alternativa); a média continua disponível.
* Potência: `EnergyCounter` — domínios `intel-rapl:N` de pacote (Intel e
  AMD), ou hwmon `zenergy`/`amd_energy` ("Esocket"). Delta de energia ÷
  delta de tempo, com tratamento de *wraparound* por `max_energy_range_uj`,
  descarte de valores absurdos (> 1500 W) e estados `ok`, `warming`,
  `permission`, `unavailable`, `invalid`. **Nunca 0 W por falha.**

## Multi-dispositivo

Cada cooler é um `DisplaySession` independente, como cada painel: um
AK620 e um painel Turing no mesmo computador têm laços, estados e
recuperação separados (teste `test_runtime_drives_a_cooler_next_to_a_raster_panel`).
