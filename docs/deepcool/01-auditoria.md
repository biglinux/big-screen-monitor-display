# 01 — Auditoria (integração DeepCool Digital)

Levantamento feito sobre o commit `8cb0c24` (v5.0.0), antes de qualquer
alteração, na branch `feat/deepcool-digital`. Máquina de desenvolvimento:
Ryzen 7 5700G, Manjaro, kernel 6.18. **Nenhum cooler DeepCool estava
conectado** (`lsusb` não lista o fabricante `3633`); toda a validação
descrita nesta pasta é, portanto, de software (ver [07-testes](07-testes.md)).

## Estado encontrado

| Área | Situação antes | Consequência para a DeepCool |
| --- | --- | --- |
| Contrato de driver (`bsmd/displays/base.py`) | Só existia saída *raster*: o runtime renderiza uma imagem do tamanho do painel e chama `driver.present(image)` | Coolers numéricos não têm framebuffer: precisam de outro tipo de saída |
| Descoberta (`discovery.py`) | Lê VID/PID, serial, `tty*` do sysfs | Faltava localizar os nós `hidraw` do dispositivo |
| Registro (`registry.py`) | Perfis de painéis LCD (AX206, Turing, XuanFang, Kipye, WeAct) | Sem nenhum perfil para o VID `3633` |
| Telemetria (`telemetry.py`) | Temperatura da CPU pelo primeiro sensor encontrado, frequência média, uso | Sem potência da CPU; sem frequência do núcleo mais rápido; temperatura sem preferência Tdie/Tctl/Package |
| Potência (RAPL) | Não lida | `energy_uj` é legível só pelo root desde o CVE-2020-8694 |
| udev | Regras restritas por VID/PID para os painéis, grupo `big-screen-monitor`, `uaccess` | Nenhuma regra para `hidraw` nem para `3633` |
| systemd | `DynamicUser`, `DevicePolicy=closed`, `DeviceAllow` para USB e serial | `hidraw` bloqueado pelo sandbox |
| Interface | Cartões e páginas de detalhe pressupõem largura × altura em pixels | Um dispositivo 0×0 quebraria miniaturas e a proporção da prévia |

## Projetos de referência analisados

Clonados apenas para leitura; nenhum código foi copiado — os formatos de
bytes foram reimplementados a partir da descrição e conferidos com os
exemplos de cada projeto.

| Projeto | Licença | Cobertura | O que foi aproveitado |
| --- | --- | --- | --- |
| Nortank12/deepcool-digital-linux | GPL-3.0 | AK, AG, LS, AK PRO, LD, CH, LP, MORPHEUS | Tabela de PIDs, layouts HID, cabeçalhos estruturados, init do LD |
| raghulkrishna/deepcool-ak620-digital-linux | MIT | AK620 | Confirmação do modo/barra/dígitos |
| Algorithm0/deepcool-digital-info | MIT | AK | Variantes SE (sem report id) |
| mymymy1303/qt-deepcool | MIT | MYSTIQUE | Moldura AA 2E, checksum, comandos |
| dinoyoshi/serial-lcd-panel-client | MIT | MYSTIQUE 240 | Sequência de init em Machine Info confirmada em hardware, captura real usada no teste do checksum, alerta sobre upload de imagens |

O projeto é GPL-3.0-or-later, compatível com todas as licenças acima.

## Riscos identificados

1. **Escrita no dispositivo errado** — um hidraw genérico pode ser teclado,
   mouse ou outro periférico. Mitigação: só abrir nós cujo `HIDIOCGRAWINFO`
   confirme VID `3633` e o PID esperado.
2. **Permissões amplas** — a solução comum dos projetos de referência é
   `MODE="0666"` em todo `hidraw`. Rejeitada: regra restrita por VID/PID e
   grupo do serviço.
3. **Potência falsa** — mostrar 0 W quando a leitura falha engana o usuário.
   Mitigação: valor ausente com motivo (`permission`, `warming`, …).
4. **MYSTIQUE e upload de imagens** — a transferência de imagens grava na
   memória persistente; o relato de hardware real é que o cooler deixa de
   voltar ao modo de informações. Mitigação: o comando não existe no código.
5. **Dois programas no mesmo cooler** — pacotes intercalados. Mitigação:
   `flock` exclusivo no nó e detecção (somente leitura) de serviços conhecidos.
6. **Alarmes do firmware** — AK PRO e LD têm limites internos. Nada é enviado
   para alterá-los.
