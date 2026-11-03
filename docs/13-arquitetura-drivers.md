# 13 — Arquitetura dos drivers

```
bsmd/displays/
├── base.py          contrato, erros, Capabilities, RasterDriver (diff/retângulos)
├── transport.py     SerialTransport (timeouts, exclusivo, classificação de erros)
├── registry.py      famílias: regras de identificação, classe de validação, fábrica
├── discovery.py     sysfs -> candidatos (somente leitura)
├── ax206.py  turing_serial.py  xuanfang.py  kipye.py  weact.py  turing_usb.py
├── des.py           DES-CBC mínimo (cabeçalho Turing USB)
└── simulated.py
bsmd/drivers.py      camada de compatibilidade com a API 3.x/4.0
```

## Contrato

Todo driver expõe:

| Membro | Função |
| --- | --- |
| `open()` | conecta, faz o handshake **da família indicada pelo registro** e deixa o painel pronto para quadros paisagem de `native_size` |
| `present(image)` | envia um quadro; devolve `Transfer(bytes, rects, full, duration)` |
| `set_brightness(percent)` | 0–100, convertido para a escala do painel |
| `probe()` | verificação barata de vida (porta existe, sinais de modem legíveis, SYNC) |
| `invalidate()` | esquece o último quadro: o próximo vai inteiro |
| `close()` | nunca lança exceção; pode ser chamado duas vezes |
| `capabilities` | codificação, passos de brilho, atualização parcial, LEDs, sensores, forma, payload máximo |

O runtime gira os quadros para retrato e orientações invertidas
(`frames.to_native`), então nenhum driver precisa de rotação própria além da
que o protocolo exige.

## RasterDriver

Base comum das famílias que aceitam retângulos. Detecta mudanças em RGB888
empacotado (painéis BGRA não perdem cores finas), planeja retângulos em uma
grade de tiles por família e manda o quadro inteiro quando a área alterada
passa de `FULL_REFRESH_RATIO`. Famílias sem atualização parcial (Turing USB)
enviam só quando algo mudou.

| Família | Tile | Máx. retângulos | Observação |
| --- | --- | --- | --- |
| AX206 | 32×16 | 24 | ~0,3 ms de overhead SCSI por retângulo |
| Turing rev. A | 48×20 | 48 | |
| XuanFang rev. B | herdado | 16 | pausa de 50 ms por bitmap |
| Turing rev. C | 48×24 | 4 | cada parcial espera status; inteiro acima de 40% |
| WeAct A / B | 32×16 / 16×16 | 16 / 8 | |
| Turing USB | — | quadro inteiro | PNG/JPEG |

## Registro e fábrica

`Profile` descreve a família (nome, modelos, resoluções, protocolo,
transporte, regras, classe, referência, opções). `Rule` casa VID, PIDs,
serial exato ou prefixo, e marca painéis dormindo ou dicas de tamanho.
`Profile.create(candidate, options)` constrói o driver sem abri-lo. As
opções vêm das configurações do display (`discovery.driver_options`):
tamanho do rev. C, cor dos LEDs, sensores.

## Recuperação

Cada display é uma `DisplaySession` (`bsmd/runtime.py`) com máquina de
estados própria (`starting → recovering → healthy ⇄ degraded`,
`disconnected/retrying/failed`), backoff exponencial, heartbeats de render
e transporte e histórico de incidentes marcado com o id do display. Falhas
fatais (desconectado, permissão, ocupado, não encontrado) ou dois erros
seguidos fecham e reabrem **só aquele** driver. O único reset de hardware é o
reset USB do próprio AX206. O processo só sai com código 3 (para o systemd
reiniciar) quando **todos** os displays estão em `failed`.

## Compatibilidade

`bsmd/drivers.py` reexporta `DisplayError`, tipos de erro, `Transfer`,
`DeviceInfo`, `AX206`, `SimulatedDisplay`, `TuringSmartScreen` (= rev. A) e
`make_driver`/`device_present`, agora baseados na descoberta universal.
